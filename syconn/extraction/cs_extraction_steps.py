# -*- coding: utf-8 -*-
# distutils: language=c++
# SyConn - Synaptic connectivity inference toolkit
#
# Copyright (c) 2016 - now
# Max Planck Institute of Neurobiology, Martinsried, Germany
# Authors: Philipp Schubert, Joergen Kornfeld

try:
    import cPickle as pkl
except ImportError:
    import pickle as pkl
import glob
import numpy as np
import scipy.ndimage
from knossos_utils import knossosdataset
from knossos_utils import chunky
knossosdataset._set_noprint(True)
import os
from ..mp import batchjob_utils as qu
from ..handler import compression
from ..handler.basics import kd_factory
from . import log_extraction
from .object_extraction_wrapper import from_ids_to_objects
try:
    from .block_processing_cython import kernel, process_block, process_block_nonzero
except ImportError as e:
    log_extraction.warning('Could not import cython version of `block_processing`.')
    from .block_processing import kernel, process_block, process_block_nonzero


def find_contact_sites(cset, knossos_path, filename='cs', n_max_co_processes=None,
                       qsub_pe=None, qsub_queue=None):
    os.makedirs(cset.path_head_folder, exist_ok=True)
    multi_params = []
    for chunk in cset.chunk_dict.values():
        multi_params.append([chunk, knossos_path, filename])

    # if (qsub_pe is None and qsub_queue is None) or not qu.batchjob_enabled():
    #     results = sm.start_multiprocess_imap(_contact_site_detection_thread, multi_params,
    #                                          debug=False, nb_cpus=n_max_co_processes)
    # elif qu.batchjob_enabled():
    path_to_out = qu.QSUB_script(multi_params,
                                 "contact_site_detection",
                                 script_folder=None,
                                 n_max_co_processes=n_max_co_processes,
                                 pe=qsub_pe, queue=qsub_queue)

    out_files = glob.glob(path_to_out + "/*")
    results = []
    for out_file in out_files:
        with open(out_file, 'rb') as f:
            results.append(pkl.load(f))
    # else:
    #     raise Exception("QSUB not available")
    chunky.save_dataset(cset)


def _contact_site_detection_thread(args):
    chunk = args[0]
    knossos_path = args[1]
    filename = args[2]

    kd = kd_factory(knossos_path)

    overlap = np.array([6, 6, 3], dtype=np.int)
    offset = np.array(chunk.coordinates - overlap)
    size = 2 * overlap + np.array(chunk.size)
    data = kd.from_overlaycubes_to_matrix(size, offset, datatype=np.uint64).astype(np.uint32)
    contacts = detect_cs(data)
    os.makedirs(chunk.folder, exist_ok=True)
    compression.save_to_h5py([contacts],
                             chunk.folder + filename +
                             ".h5", ["cs"])


def detect_cs(arr):
    jac = np.zeros([3, 3, 3], dtype=np.int)
    jac[1, 1, 1] = -6
    jac[1, 1, 0] = 1
    jac[1, 1, 2] = 1
    jac[1, 0, 1] = 1
    jac[1, 2, 1] = 1
    jac[2, 1, 1] = 1
    jac[0, 1, 1] = 1

    edges = scipy.ndimage.convolve(arr.astype(np.int), jac) < 0

    edges = edges.astype(np.uint32)
    # edges[arr == 0] = True
    arr = arr.astype(np.uint32)

    # cs_seg = cse.process_chunk(edges, arr, [7, 7, 3])
    cs_seg = process_block_nonzero(edges, arr, [13, 13, 7])

    return cs_seg


# TODO: use from_ids_to_objects
def extract_agg_contact_sites(cset, working_dir, filename='cs', hdf5name='cs',
                              n_folders_fs=10000, suffix="", overlaydataset_path=None,
                              n_max_co_processes=None, n_chunk_jobs=5000):

    from_ids_to_objects(cset, filename, overlaydataset_path=overlaydataset_path, n_chunk_jobs=n_chunk_jobs,
                        hdf5names=[hdf5name], n_max_co_processes=n_max_co_processes, workfolder=working_dir,
                        n_folders_fs=n_folders_fs, use_combined_extraction=True, suffix=suffix)
