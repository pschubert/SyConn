# -*- coding: utf-8 -*-
# SyConn - Synaptic connectivity inference toolkit
#
# Copyright (c) 2016 - now
# Max Planck Institute of Neurobiology, Martinsried, Germany
# Authors: Philipp Schubert, Joergen Kornfeld

import numpy as np
import re
import glob
import os
import shutil
from multiprocessing.pool import ThreadPool
try:
    import cPickle as pkl
except ImportError:
    import pickle as pkl
from knossos_utils import knossosdataset
knossosdataset._set_noprint(True)
try:
    from knossos_utils import mergelist_tools
except ImportError:
    from knossos_utils import mergelist_tools_fallback as mergelist_tools
from multiprocessing import cpu_count
from .segmentation import SegmentationDataset, SegmentationObject
from ..handler.basics import load_pkl2obj, write_obj2pkl, chunkify, kd_factory
from ..handler.config import DynConfig
from .super_segmentation_helper import create_sso_skeleton
from .super_segmentation_helper import assemble_from_mergelist
from ..mp import batchjob_utils as qu
from .super_segmentation_object import SuperSegmentationObject
from ..mp import mp_utils as sm
from .. import global_params
from . import log_reps


class SuperSegmentationDataset(object):
    def __init__(self, working_dir=None, version=None, ssd_type='ssv',
                 version_dict=None, sv_mapping=None, scaling=None, config=None,
                 sso_caching=False, sso_locking=False):
        """
        Class to hold a set of agglomerated supervoxels (SuperSegmentationObject).

        Parameters
        ----------
        working_dir : str
        version : str or int
        ssd_type : str
        version_dict : dict
        sv_mapping : dict or str
        scaling : np.array
        config : Optional[Config]
            DynConfig object, see syconn/handler/config.py
        sso_caching : bool
            WIP, enabes caching mechanisms in SuperSegmentationObjects returned via
            `get_super_segmentation_object`
        sso_locking : bool
            if True, locking is enabled for SSO files.
        """
        self.ssv_dict = {}
        self.mapping_dict = {}
        self.sso_caching = sso_caching
        self.sso_locking = sso_locking
        self._mapping_dict_reversed = None

        self._type = ssd_type
        self._id_changer = []
        self._ssv_ids = None
        self._config = config

        if working_dir is None:
            if global_params.wd is not None or version == 'tmp':
                self._working_dir = global_params.wd
            else:
                msg = "No working directory (wd) given. It has to be" \
                      " specified either in global_params, via kwarg " \
                      "`working_dir` or `config`."
                log_reps.error(msg)
                raise ValueError(msg)
        else:
            self._working_dir = working_dir
            self._config = DynConfig(working_dir)

        if global_params.wd is None:
            global_params.wd = self._working_dir

        if scaling is None:
            try:
                self._scaling = \
                    np.array(self.config.entries["Dataset"]["scaling"])
            except:
                self._scaling = np.array([1, 1, 1])
        else:
            self._scaling = scaling

        if version is None:
            try:
                self._version = self.config.entries["Versions"][self.type]
            except:
                raise Exception("unclear value for version")
        elif version == "new":
            other_datasets = glob.glob(self.working_dir + "/%s_*" % self.type)
            max_version = -1
            for other_dataset in other_datasets:
                try:
                    other_version = \
                        int(re.findall("[\d]+",
                                       os.path.basename(other_dataset))[-1])
                    if max_version < other_version:
                        max_version = other_version
                except IndexError:  # version is not an integer, found version could be e.g. 'tmp'
                    pass

            self._version = max_version + 1
        else:
            self._version = version

        if version_dict is None:
            try:
                self.version_dict = self.config.entries["Versions"]
            except:
                raise Exception("No version dict specified in config")
        else:
            if isinstance(version_dict, dict):
                self.version_dict = version_dict
            elif isinstance(version_dict, str) and version_dict == "load":
                if self.version_dict_exists:
                    self.load_version_dict()
            else:
                raise Exception("No version dict specified in config")

        if not os.path.exists(self.path):
            os.makedirs(self.path)

        if sv_mapping is not None:
            self.apply_mergelist(sv_mapping)

    def __repr__(self):
        return 'SSD of type "{}", version "{}" stored at "{}"'.format(self.type, self.version,
                                                                      self.path)

    @property
    def type(self):
        return str(self._type)

    @property
    def scaling(self):
        return self._scaling

    @property
    def working_dir(self):
        return self._working_dir

    @property
    def config(self):
        if self._config is None:
            self._config = global_params.config
        return self._config

    @property
    def path(self):
        return "%s/%s_%s/" % (self._working_dir, self.type, self.version)

    @property
    def version(self):
        return str(self._version)

    @property
    def version_dict_path(self):
        return self.path + "/version_dict.pkl"

    @property
    def mapping_dict_exists(self):
        return os.path.exists(self.mapping_dict_path)

    @property
    def mapping_dict_reversed_exists(self):
        return os.path.exists(self.mapping_dict_reversed_path)

    @property
    def mapping_dict_path(self):
        return self.path + "/mapping_dict.pkl"

    @property
    def mapping_dict_reversed_path(self):
        return self.path + "/mapping_dict_reversed.pkl"

    @property
    def id_changer_path(self):
        return self.path + "/id_changer.npy"

    @property
    def version_dict_exists(self):
        return os.path.exists(self.version_dict_path)

    @property
    def id_changer_exists(self):
        return os.path.exists(self.id_changer_path)

    @property
    def mapping_dict_reversed(self):
        if self._mapping_dict_reversed is None:
            if self.mapping_dict_reversed_exists:
                self.load_mapping_dict_reversed()
            else:
                self._mapping_dict_reversed = {}
                self.load_mapping_dict()
                for k, v in self.mapping_dict.items():
                    for ix in v:
                        self._mapping_dict_reversed[ix] = k
                self.save_mapping_dict_reversed()
        return self._mapping_dict_reversed


    @property
    def ssv_ids(self):
        if self._ssv_ids is None:
            if len(self.mapping_dict) > 0:
                self._ssv_ids = np.array(list(self.mapping_dict.keys()))
            elif self.mapping_dict_exists:
                self.load_mapping_dict()
                self._ssv_ids = np.array(list(self.mapping_dict.keys()))
            elif os.path.exists(self.path + "/ids.npy"):
                self._ssv_ids = np.load(self.path + "/ids.npy")
            else:
                paths = glob.glob(self.path + "/so_storage/*/*/*/")
                self._ssv_ids = np.array([int(os.path.basename(p.strip("/")))
                                          for p in paths], dtype=np.uint)
        return self._ssv_ids

    @property
    def ssvs(self):
        ix = 0
        tot_nb_ssvs = len(self.ssv_ids)
        while ix < tot_nb_ssvs:
            yield self.get_super_segmentation_object(self.ssv_ids[ix])
            ix += 1

    @property
    def sv_ids(self):
        self.load_mapping_dict()
        return np.concatenate(self.mapping_dict.values())

    @property
    def id_changer(self):
        # TODO: Understand reason for 'id_changer' and
        # replace it by 'mapping_dict_reversed'
        if len(self._id_changer) == 0:
            self.load_id_changer()
        return self._id_changer

    def load_cached_data(self, name):
        if os.path.exists(self.path + name + "s.npy"):
            return np.load(self.path + name + "s.npy")

    def sv_id_to_ssv_id(self, sv_id):
        return self.id_changer[sv_id]

    def get_segmentationdataset(self, obj_type):
        assert obj_type in self.version_dict
        return SegmentationDataset(obj_type, version=self.version_dict[obj_type],
                                   working_dir=self.working_dir)

    def apply_mergelist(self, sv_mapping):
        assemble_from_mergelist(self, sv_mapping)

    def get_super_segmentation_object(self, obj_id, new_mapping=False,
                                      caching=None, create=False):  # set default of `caching` to False, PS 20Feb2019
        """
        SuperSegmentationObject factory method for single ID or list of IDs.

        Parameters
        ----------
        obj_id : int or list of int
        new_mapping : bool
        caching : bool
        create : bool

        Returns
        -------
        SuperSegmentationObject or list of SuperSegmentationObject
        """
        if caching is None:
            caching = self.sso_caching
        if np.isscalar(obj_id):
            if new_mapping:
                sso = SuperSegmentationObject(obj_id,
                                              self.version,
                                              self.version_dict,
                                              self.working_dir,
                                              ssd_type=self.type,
                                              create=create,
                                              sv_ids=self.mapping_dict[obj_id],
                                              scaling=self.scaling,
                                              object_caching=caching,
                                              voxel_caching=caching,
                                              mesh_caching=caching,
                                              view_caching=caching,
                                              enable_locking_so=False,
                                              enable_locking=self.sso_locking)
            else:
                sso = SuperSegmentationObject(obj_id,
                                              self.version,
                                              self.version_dict,
                                              self.working_dir,
                                              ssd_type=self.type,
                                              create=create,
                                              scaling=self.scaling,
                                              object_caching=caching,
                                              voxel_caching=caching,
                                              mesh_caching=caching,
                                              view_caching=caching,
                                              enable_locking_so=False,
                                              enable_locking=self.sso_locking)
            sso._dataset = self
        else:
            sso = []
            for ix in obj_id:
                # call it with scalar input recursively
                sso.append(self.get_super_segmentation_object(ix, create=create,
                           new_mapping=new_mapping, caching=caching))
        return sso

    def save_dataset_shallow(self):
        self.save_version_dict()
        self.save_mapping_dict()
        self.save_id_changer()

    def save_dataset_deep(self, extract_only=False, attr_keys=(), n_jobs=None,
                          qsub_pe=None, qsub_queue=None, nb_cpus=None,
                          n_max_co_processes=None, new_mapping=True):
        save_dataset_deep(self, extract_only=extract_only,
                          attr_keys=attr_keys, n_jobs=n_jobs,
                          qsub_pe=qsub_pe, qsub_queue=qsub_queue,
                          nb_cpus=nb_cpus, new_mapping=new_mapping,
                          n_max_co_processes=n_max_co_processes)

    def reskeletonize_objects(self, stride=200, small=True, big=True,
                              qsub_pe=None, qsub_queue=None, nb_cpus=1,
                              n_max_co_processes=None):
        multi_params = []
        for ssv_id_block in [self.ssv_ids[i:i + stride]
                             for i in
                             range(0, len(self.ssv_ids), stride)]:
            multi_params.append([ssv_id_block, self.version, self.version_dict,
                                 self.working_dir])

        if small:
            if (qsub_pe is None and qsub_queue is None) or not qu.batchjob_enabled():
                results = sm.start_multiprocess(
                    reskeletonize_objects_small_ones_thread,
                    multi_params, nb_cpus=nb_cpus)

            elif qu.batchjob_enabled():
                path_to_out = qu.QSUB_script(multi_params,
                                             "reskeletonize_objects_small_ones",
                                             n_cores=nb_cpus,
                                             pe=qsub_pe, queue=qsub_queue,
                                             script_folder=None,
                                             n_max_co_processes=
                                             n_max_co_processes)
            else:
                raise Exception("QSUB not available")

        if big:
            if (qsub_pe is None and qsub_queue is None) or not qu.batchjob_enabled():
                results = sm.start_multiprocess(
                    reskeletonize_objects_big_ones_thread,
                    multi_params, nb_cpus=1)

            elif qu.batchjob_enabled():
                path_to_out = qu.QSUB_script(multi_params,
                                             "reskeletonize_objects_big_ones",
                                             n_cores=10,
                                             n_max_co_processes=int(n_max_co_processes/10*nb_cpus),
                                             remove_jobfolder=True)
            else:
                raise Exception("QSUB not available")

    def export_skeletons(self, obj_types, apply_mapping=True, stride=1000,
                         qsub_pe=None, qsub_queue=None, nb_cpus=1):
        # TODO: there is another `export_skeletons` defined outside this class, refactor!
        multi_params = []
        for ssv_id_block in [self.ssv_ids[i:i + stride]
                             for i in
                             range(0, len(self.ssv_ids), stride)]:
            multi_params.append([ssv_id_block, self.version, self.version_dict,
                                 self.working_dir, obj_types, apply_mapping])

        if (qsub_pe is None and qsub_queue is None) or not qu.batchjob_enabled():
            results = sm.start_multiprocess(
                reskeletonize_objects_small_ones_thread,
                multi_params, nb_cpus=nb_cpus)
            no_skel_cnt = np.sum(results)

        elif qu.batchjob_enabled():
            path_to_out = qu.QSUB_script(multi_params,
                                         "export_skeletons",
                                         n_cores=nb_cpus, remove_jobfolder=True)
            out_files = glob.glob(path_to_out + "/*")
            no_skel_cnt = 0
            for out_file in out_files:
                with open(out_file, 'rb') as f:
                    no_skel_cnt += np.sum(pkl.load(f))

        else:
            raise Exception("QSUB not available")

        print("N no skeletons: %d" % no_skel_cnt)

    def associate_objs_with_skel_nodes(self, obj_types, stride=1000,
                                       qsub_pe=None, qsub_queue=None,
                                       nb_cpus=1):
        multi_params = []
        for ssv_id_block in [self.ssv_ids[i:i + stride]
                             for i in
                             range(0, len(self.ssv_ids), stride)]:
            multi_params.append([ssv_id_block, self.version, self.version_dict,
                                 self.working_dir, obj_types])

        if (qsub_pe is None and qsub_queue is None) or not qu.batchjob_enabled():
            results = sm.start_multiprocess(
                associate_objs_with_skel_nodes_thread,
                multi_params, nb_cpus=nb_cpus)
            no_skel_cnt = np.sum(results)

        elif qu.batchjob_enabled():
            path_to_out = qu.QSUB_script(multi_params,
                                         "associate_objs_with_skel_nodes",
                                         n_cores=nb_cpus, remove_jobfolder=True)
        else:
            raise Exception("QSUB not available")

    def predict_axoness_skelbased(self, stride=1000, qsub_pe=None, qsub_queue=None,
                        nb_cpus=1):
        multi_params = []
        for ssv_id_block in [self.ssv_ids[i:i + stride]
                             for i in
                             range(0, len(self.ssv_ids), stride)]:
            multi_params.append([ssv_id_block, self.version, self.version_dict,
                                 self.working_dir])

        if (qsub_pe is None and qsub_queue is None) or not qu.batchjob_enabled():
            results = sm.start_multiprocess(
                predict_axoness_skelbased_thread,
                multi_params, nb_cpus=nb_cpus)

        elif qu.batchjob_enabled():
            path_to_out = qu.QSUB_script(multi_params,
                                         "predict_axoness_skelbased",
                                         n_cores=nb_cpus, remove_jobfolder=True)
        else:
            raise Exception("QSUB not available")

    def predict_cell_types_skelbased(self, stride=1000, qsub_pe=None, qsub_queue=None,
                           nb_cpus=1):
        multi_params = []
        for ssv_id_block in [self.ssv_ids[i:i + stride]
                             for i in
                             range(0, len(self.ssv_ids), stride)]:
            multi_params.append([ssv_id_block, self.version, self.version_dict,
                                 self.working_dir])

        if (qsub_pe is None and qsub_queue is None) or not qu.batchjob_enabled():
            results = sm.start_multiprocess(
                predict_cell_type_skelbased_thread,
                multi_params, nb_cpus=nb_cpus)

        elif qu.batchjob_enabled():
            path_to_out = qu.QSUB_script(multi_params,
                                         "predict_cell_type_skelbased",
                                         n_cores=nb_cpus, remove_jobfolder=True)
        else:
            raise Exception("QSUB not available")

    def save_version_dict(self):
        if len(self.version_dict) > 0:
            write_obj2pkl(self.version_dict_path, self.version_dict)

    def load_version_dict(self):
        assert self.version_dict_exists
        self.version_dict = load_pkl2obj(self.version_dict_path)

    def save_mapping_dict(self):
        if len(self.mapping_dict) > 0:
            write_obj2pkl(self.mapping_dict_path, self.mapping_dict)

    def save_mapping_dict_reversed(self):
        if len(self.mapping_dict_reversed) > 0:
            write_obj2pkl(self.mapping_dict_reversed_path,
                          self._mapping_dict_reversed)

    def load_mapping_dict(self):
        assert self.mapping_dict_exists
        self.mapping_dict = load_pkl2obj(self.mapping_dict_path)

    def load_mapping_dict_reversed(self):
        assert self.mapping_dict_reversed_exists
        self._mapping_dict_reversed = load_pkl2obj(self.mapping_dict_reversed_path)

    def save_id_changer(self):
        if len(self._id_changer) > 0:
            np.save(self.id_changer_path, self._id_changer)

    def load_id_changer(self):
        assert self.id_changer_exists
        self._id_changer = np.load(self.id_changer_path)


def save_dataset_deep(ssd, extract_only=False, attr_keys=(), n_jobs=None,
                      qsub_pe=None, qsub_queue=None, nb_cpus=None,
                      n_max_co_processes=None, new_mapping=True):
    # TODO: remove `qsub_pe`and `qsub_queue`
    """
    Saves attributes of all SSVs within the given SSD and computes properties
    like size and representative coordinate. `ids.npy` order may change after
    repeated runs.
    TODO: make this method deterministic and allow partial
     updates of a subset of attributes (e.g. use already existing `ids.npy` in
     case of updating, aka `extract_only=True`)

    Parameters
    ----------
    ssd : SuperSegmentationDataset
    extract_only : bool
     Only cache attributes (see`attr_keys` from attribute dict. This will add
      a suffix `_sel` to the numpy cache array file names (-> updates will not
      apply to the `load_cached_data` method).
    attr_keys : List[str]
        Attributes to cache, only used if `extract_only=True`
    n_jobs : int
    qsub_pe : str
        Currently requires any string to enable batch job system,
        will be replaced by a global flag soon
    qsub_queue : str
        Currently requires any string to enable batch job system,
        will be replaced by a global flag soon
    nb_cpus : int
        CPUs per worker
    n_max_co_processes : int
        Number of parallel worker
    new_mapping :
        Whether to apply new mapping (see `ssd.mapping_dict`)
    """
    ssd.save_dataset_shallow()
    if n_jobs is None:
        n_jobs = global_params.NCORE_TOTAL
    multi_params = chunkify(ssd.ssv_ids, n_jobs)
    multi_params = [(ssv_id_block, ssd.version, ssd.version_dict,
                     ssd.working_dir, extract_only, attr_keys,
                     ssd._type, new_mapping) for ssv_id_block in multi_params]

    if not qu.batchjob_enabled():
        results = sm.start_multiprocess(
            _write_super_segmentation_dataset_thread,
            multi_params, nb_cpus=nb_cpus)

    else:
        path_to_out = qu.QSUB_script(multi_params,
                                     "write_super_segmentation_dataset",
                                     n_cores=nb_cpus,
                                     n_max_co_processes=n_max_co_processes)

        out_files = glob.glob(path_to_out + "/*")
        results = []
        for out_file in out_files:
            with open(out_file, 'rb') as f:
                results.append(pkl.load(f))
        shutil.rmtree(os.path.abspath(path_to_out + "/../"), ignore_errors=True)
    attr_dict = {}
    for this_attr_dict in results:
        for attribute in this_attr_dict.keys():
            if not attribute in attr_dict:
                attr_dict[attribute] = []

            attr_dict[attribute] += this_attr_dict[attribute]

    if not ssd.mapping_dict_exists:
        ssd.mapping_dict = dict(zip(attr_dict["id"], attr_dict["sv"]))
        ssd.save_dataset_shallow()

    for attribute in attr_dict.keys():
        if extract_only:
            np.save(ssd.path + "/%ss_sel.npy" % attribute,  # Why '_sel'?
                    attr_dict[attribute])
        else:
            np.save(ssd.path + "/%ss.npy" % attribute,
                    attr_dict[attribute])
    log_reps.info('Finished `save_dataset_deep`of {}.'.format(repr(ssd)))


def _write_super_segmentation_dataset_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    extract_only = args[4]
    attr_keys = args[5]
    ssd_type = args[6]
    new_mapping = args[7]

    ssd = SuperSegmentationDataset(working_dir=working_dir, version=version,
                                   ssd_type=ssd_type, version_dict=version_dict)

    try:
        ssd.load_mapping_dict()
        mapping_dict_avail = True
    except:
        mapping_dict_avail = False

    attr_dict = dict(id=[])

    for ssv_obj_id in ssv_obj_ids:
        ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id,
                                                    new_mapping=new_mapping,
                                                    create=True)
        if ssv_obj.attr_dict_exists:
            ssv_obj.load_attr_dict()

        if not extract_only:

            if len(ssv_obj.attr_dict["sv"]) == 0:
                if mapping_dict_avail:
                    ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id, True)

                    if ssv_obj.attr_dict_exists:
                        ssv_obj.load_attr_dict()
                else:
                    raise Exception("No mapping information found")
        if not extract_only:
            if "rep_coord" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["rep_coord"] = ssv_obj.rep_coord
            if "bounding_box" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["bounding_box"] = ssv_obj.bounding_box
            if "size" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["size"] = ssv_obj.size

        ssv_obj.attr_dict["sv"] = np.array(ssv_obj.attr_dict["sv"],
                                           dtype=np.int)
        if extract_only:
            ignore = False
            for attribute in attr_keys:
                if not attribute in ssv_obj.attr_dict:
                    ignore = True
                    break
            if ignore:
                continue

            attr_dict["id"].append(ssv_obj_id)

            for attribute in attr_keys:
                if attribute not in attr_dict:
                    attr_dict[attribute] = []

                if attribute in ssv_obj.attr_dict:
                    attr_dict[attribute].append(ssv_obj.attr_dict[attribute])
                else:
                    attr_dict[attribute].append(None)
        else:
            attr_dict["id"].append(ssv_obj_id)
            for attribute in ssv_obj.attr_dict.keys():
                if attribute not in attr_dict:
                    attr_dict[attribute] = []

                attr_dict[attribute].append(ssv_obj.attr_dict[attribute])

            ssv_obj.save_attr_dict()
    return attr_dict


def export_to_knossosdataset(ssd, kd, stride=1000, qsub_pe=None,
                             qsub_queue=None, nb_cpus=10):
    multi_params = []
    for ssv_id_block in [ssd.ssv_ids[i:i + stride]
                         for i in range(0, len(ssd.ssv_ids), stride)]:
        multi_params.append([ssv_id_block, ssd.version, ssd.version_dict,
                             ssd.working_dir, kd.knossos_path, nb_cpus])

    if (qsub_pe is None and qsub_queue is None) or not qu.batchjob_enabled():
        results = sm.start_multiprocess(_export_ssv_to_knossosdataset_thread,
                                        multi_params, nb_cpus=nb_cpus)

    elif qu.batchjob_enabled():
        path_to_out = qu.QSUB_script(multi_params,
                                     "export_ssv_to_knossosdataset",
                                     remove_jobfolder=True)

    else:
        raise Exception("QSUB not available")


def _export_ssv_to_knossosdataset_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    kd_path = args[4]
    nb_threads = args[5]

    kd = knossosdataset.KnossosDataset().initialize_from_knossos_path(kd_path)

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_obj_id in ssv_obj_ids:
        ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id, True)

        offset = ssv_obj.bounding_box[0]
        if not 0 in offset:
            kd.from_matrix_to_cubes(offset,
                                    data=ssv_obj.voxels.astype(np.uint64) *
                                         ssv_obj_id,
                                    overwrite=False,
                                    nb_threads=nb_threads)


def convert_knossosdataset(ssd, sv_kd_path, ssv_kd_path,
                           stride=256, qsub_pe=None, qsub_queue=None,
                           nb_cpus=None):
    ssd.save_dataset_shallow()
    sv_kd = kd_factory(sv_kd_path)

    if not os.path.exists(ssv_kd_path):
        ssv_kd = knossosdataset.KnossosDataset()
        ssv_kd.initialize_without_conf(ssv_kd_path, sv_kd.boundary,
                                       sv_kd.scale,
                                       sv_kd.experiment_name,
                                       mags=[1])

    size = np.ones(3, dtype=np.int) * stride
    multi_params = []
    offsets = []
    for x in range(0, sv_kd.boundary[0], stride):
        for y in range(0, sv_kd.boundary[1], stride):
            for z in range(0, sv_kd.boundary[2], stride):
                offsets.append([x, y, z])
                if len(offsets) >= 20:
                    multi_params.append([ssd.version, ssd.version_dict,
                                         ssd.working_dir, nb_cpus,
                                         sv_kd_path, ssv_kd_path, offsets,
                                         size])
                    offsets = []

    if len(offsets) > 0:
        multi_params.append([ssd.version, ssd.version_dict,
                             ssd.working_dir, nb_cpus,
                             sv_kd_path, ssv_kd_path, offsets,
                             size])

    if (qsub_pe is None and qsub_queue is None) or not qu.batchjob_enabled():
        results = sm.start_multiprocess(_convert_knossosdataset_thread,
                                        multi_params, nb_cpus=nb_cpus)

    elif qu.batchjob_enabled():
        path_to_out = qu.QSUB_script(multi_params,
                                     "convert_knossosdataset",
                                     pe=qsub_pe, queue=qsub_queue,
                                     script_folder=None)

    else:
        raise Exception("QSUB not available")


def _convert_knossosdataset_thread(args):
    version = args[0]
    version_dict = args[1]
    working_dir = args[2]
    nb_threads = args[3]
    sv_kd_path = args[4]
    ssv_kd_path = args[5]
    offsets = args[6]
    size = args[7]

    sv_kd = kd_factory(sv_kd_path)
    ssv_kd = kd_factory(ssv_kd_path)

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_id_changer()

    for offset in offsets:
        block = sv_kd.from_overlaycubes_to_matrix(size, offset,
                                                  datatype=np.uint32,
                                                  nb_threads=nb_threads)

        block = ssd.id_changer[block]

        ssv_kd.from_matrix_to_cubes(offset,
                                    data=block.astype(np.uint32),
                                    datatype=np.uint32,
                                    overwrite=False,
                                    nb_threads=nb_threads)

        raw = sv_kd.from_raw_cubes_to_matrix(size, offset,
                                             nb_threads=nb_threads)

        ssv_kd.from_matrix_to_cubes(offset,
                                    data=raw,
                                    datatype=np.uint8,
                                    as_raw=True,
                                    overwrite=False,
                                    nb_threads=nb_threads)


def export_skeletons(ssd, obj_types, apply_mapping=True, stride=1000,
                     qsub_pe=None, qsub_queue=None, nb_cpus=1):
    multi_params = []
    for ssv_id_block in [ssd.ssv_ids[i:i + stride]
                         for i in
                         range(0, len(ssd.ssv_ids), stride)]:
        multi_params.append([ssv_id_block, ssd.version, ssd.version_dict,
                             ssd.working_dir, obj_types, apply_mapping])

    if (qsub_pe is None and qsub_queue is None) or not qu.batchjob_enabled():
        results = sm.start_multiprocess(
            export_skeletons_thread,
            multi_params, nb_cpus=nb_cpus)
        no_skel_cnt = np.sum(results)

    elif qu.batchjob_enabled():
        path_to_out = qu.QSUB_script(multi_params,
                                     "export_skeletons",
                                     n_cores=nb_cpus,)
        out_files = glob.glob(path_to_out + "/*")
        no_skel_cnt = 0
        for out_file in out_files:
            with open(out_file, 'rb') as f:
                no_skel_cnt += np.sum(pkl.load(f))

    else:
        raise Exception("QSUB not available")

    # log_reps.info("N no skeletons: %d" % no_skel_cnt)
    log_reps.info("N missing skeletons during 'export_skeletons': %d" % no_skel_cnt)


def load_voxels_downsampled(sso, downsampling=(2, 2, 1), nb_threads=10):
    def _load_sv_voxels_thread(args):
        sv_id = args[0]
        sv = SegmentationObject(sv_id, obj_type="sv", version=sso.version_dict["sv"],
                                working_dir=sso.working_dir, config=sso.config,
                                voxel_caching=False)
        if sv.voxels_exist:
            box = [np.array(sv.bounding_box[0] - sso.bounding_box[0],
                            dtype=np.int)]

            box[0] /= downsampling
            size = np.array(sv.bounding_box[1] -
                            sv.bounding_box[0], dtype=np.float)
            size = np.ceil(size.astype(np.float) /
                           downsampling).astype(np.int)

            box.append(box[0] + size)

            sv_voxels = sv.voxels
            if not isinstance(sv_voxels, int):
                sv_voxels = sv_voxels[::downsampling[0],
                            ::downsampling[1],
                            ::downsampling[2]]

                voxels[box[0][0]: box[1][0],
                box[0][1]: box[1][1],
                box[0][2]: box[1][2]][sv_voxels] = True

    downsampling = np.array(downsampling, dtype=np.int)

    if len(sso.sv_ids) == 0:
        return None

    voxel_box_size = sso.bounding_box[1] - sso.bounding_box[0]
    voxel_box_size = voxel_box_size.astype(np.float)

    voxel_box_size = np.ceil(voxel_box_size / downsampling).astype(np.int)

    voxels = np.zeros(voxel_box_size, dtype=np.bool)

    multi_params = []
    for sv_id in sso.sv_ids:
        multi_params.append([sv_id])

    if nb_threads > 1:
        pool = ThreadPool(nb_threads)
        pool.map(_load_sv_voxels_thread, multi_params)
        pool.close()
        pool.join()
    else:
        map(_load_sv_voxels_thread, multi_params)

    return voxels


def associate_objs_with_skel_nodes_thread(args):
    # TODO: check functionality and whether this is deprecated, use 'skel_features'!
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    obj_types = args[4]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)
        ssv.load_skeleton()
        if len(ssv.skeleton["nodes"]) > 0:
            ssv.associate_objs_with_skel_nodes(obj_types)


def predict_axoness_skelbased_thread(args):
    """Skeleton-based axoness prediction"""
    # TODO: check functionality, use 'predict_nodes'!
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)

        if not ssv.load_skeleton():
            continue

        ssv.load_attr_dict()
        if "assoc_sj" in ssv.attr_dict:
            ssv.predict_axoness(feature_context_nm=5000, clf_name="rfc")
        elif len(ssv.skeleton["nodes"]) > 0:
            try:
                ssv.associate_objs_with_skel_nodes(("sj", "mi", "vc"))
                ssv.predict_axoness(feature_context_nm=5000, clf_name="rfc")
            except:
                pass


def predict_cell_type_skelbased_thread(args):
    """Skeleton-based celltype prediction"""
    # TODO: check functionality, use 'predict_nodes'!
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)

        if not ssv.load_skeleton():
            continue

        ssv.load_attr_dict()
        if "assoc_sj" in ssv.attr_dict:
            ssv.predict_cell_type(feature_context_nm=25000, clf_name="rfc")
        elif len(ssv.skeleton["nodes"]) > 0:
            try:
                ssv.associate_objs_with_skel_nodes(("sj", "mi", "vc"))
                ssv.predict_cell_type(feature_context_nm=25000, clf_name="rfc")
            except:
                pass


def export_skeletons_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    obj_types = args[4]
    apply_mapping = args[5]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    no_skel_cnt = 0
    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)

        try:
            ssv.load_skeleton()
            skeleton_avail = True
        except:
            skeleton_avail = False
            no_skel_cnt += 1

        if not skeleton_avail:
            continue

        if ssv.size == 0:
            continue

        if len(ssv.skeleton["nodes"]) == 0:
            continue

        try:
            ssv.save_skeleton_to_kzip()

            for obj_type in obj_types:
                if apply_mapping:
                    if obj_type == "sj":
                        correct_for_background = True
                    else:
                        correct_for_background = False
                    ssv.apply_mapping_decision(obj_type,
                                               correct_for_background=correct_for_background)

            ssv.save_objects_to_kzip_sparse(obj_types)

        except:
            pass

    return no_skel_cnt


def export_to_knossosdataset_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    kd_path = args[4]
    nb_threads = args[5]

    kd = knossosdataset.KnossosDataset().initialize_from_knossos_path(kd_path)

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_obj_id in ssv_obj_ids:
        ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id, True)

        offset = ssv_obj.bounding_box[0]
        if not 0 in offset:
            kd.from_matrix_to_cubes(ssv_obj.bounding_booffset,
                                    data=ssv_obj.voxels.astype(np.uint32) *
                                         ssv_obj_id,
                                    overwrite=False,
                                    nb_threads=nb_threads)


def convert_knossosdataset_thread(args):
    version = args[0]
    version_dict = args[1]
    working_dir = args[2]
    nb_threads = args[3]
    sv_kd_path = args[4]
    ssv_kd_path = args[5]
    offsets = args[6]
    size = args[7]

    sv_kd = knossosdataset.KnossosDataset()
    sv_kd.initialize_from_knossos_path(sv_kd_path)
    ssv_kd = knossosdataset.KnossosDataset()
    ssv_kd.initialize_from_knossos_path(ssv_kd_path)

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_id_changer()

    for offset in offsets:
        block = sv_kd.from_overlaycubes_to_matrix(size, offset,
                                                  datatype=np.uint32,
                                                  nb_threads=nb_threads)

        block = ssd.id_changer[block]

        ssv_kd.from_matrix_to_cubes(offset,
                                    data=block.astype(np.uint32),
                                    datatype=np.uint32,
                                    overwrite=False,
                                    nb_threads=nb_threads)

        raw = sv_kd.from_raw_cubes_to_matrix(size, offset,
                                             nb_threads=nb_threads)

        ssv_kd.from_matrix_to_cubes(offset,
                                    data=raw,
                                    datatype=np.uint8,
                                    as_raw=True,
                                    overwrite=False,
                                    nb_threads=nb_threads)


def reskeletonize_objects_small_ones_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id, True)
        if np.product(ssv.shape) > 1e10:
            continue
        # elif np.product(ssv.shape) > 10**3:
        #     ssv.calculate_skeleton(coord_scaling=(8, 8, 4))
        elif ssv.size > 0:
            ssv.calculate_skeleton(coord_scaling=(8, 8, 4), plain=True)
        else:
            ssv.skeleton = {"nodes": [], "edges": [], "diameters": []}
        ssv.save_skeleton()
        ssv.clear_cache()


def reskeletonize_objects_big_ones_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)
    ssd.load_mapping_dict()

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id, True)
        if np.product(ssv.shape) > 1e10:
            ssv.calculate_skeleton(coord_scaling=(10, 10, 5), plain=True)
        else:
            continue
        ssv.save_skeleton()
        ssv.clear_cache()


def write_super_segmentation_dataset_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    extract_only = args[4]
    attr_keys = args[5]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)

    try:
        ssd.load_mapping_dict()
        mapping_dict_avail = True
    except:
        mapping_dict_avail = False

    attr_dict = dict(id=[])

    for ssv_obj_id in ssv_obj_ids:
        ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id,
                                                    new_mapping=True,
                                                    create=True)

        if ssv_obj.attr_dict_exists:
            ssv_obj.load_attr_dict()

        if not extract_only:

            if len(ssv_obj.attr_dict["sv"]) == 0:
                if mapping_dict_avail:
                    ssv_obj = ssd.get_super_segmentation_object(ssv_obj_id, True)

                    if ssv_obj.attr_dict_exists:
                        ssv_obj.load_attr_dict()
                else:
                    raise Exception("No mapping information found")
        if not extract_only:
            if "rep_coord" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["rep_coord"] = ssv_obj.rep_coord
            if "bounding_box" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["bounding_box"] = ssv_obj.bounding_box
            if "size" not in ssv_obj.attr_dict:
                ssv_obj.attr_dict["size"] = ssv_obj.size

        ssv_obj.attr_dict["sv"] = np.array(ssv_obj.attr_dict["sv"],
                                           dtype=np.int)

        if extract_only:
            ignore = False
            for attribute in attr_keys:
                if not attribute in ssv_obj.attr_dict:
                    ignore = True
                    break
            if ignore:
                continue

            attr_dict["id"].append(ssv_obj_id)

            for attribute in attr_keys:
                if attribute not in attr_dict:
                    attr_dict[attribute] = []

                if attribute in ssv_obj.attr_dict:
                    attr_dict[attribute].append(ssv_obj.attr_dict[attribute])
                else:
                    attr_dict[attribute].append(None)
        else:
            attr_dict["id"].append(ssv_obj_id)
            for attribute in ssv_obj.attr_dict.keys():
                if attribute not in attr_dict:
                    attr_dict[attribute] = []

                attr_dict[attribute].append(ssv_obj.attr_dict[attribute])

                ssv_obj.save_attr_dict()

    return attr_dict


def copy_ssvs2new_SSD_simple(ssvs, new_version, target_wd=None, n_jobs=1,
                             safe=True):
    """
    Creates a new SSD specified with 'version' with a copy of the given SSVs.
    Usually used for generating distinct GT SSDs. Based on the common supervoxel
    dataset (e.g. `ssv_0`).

    Parameters
    ----------
    ssvs : List[SuperSegmentationObject]
        source SuperSegmentationObjects taken from default SSD in working directory
    new_version : str
        version of the new SSV SuperSegmentationDataset where SSVs will be copied to
    target_wd :
        path to working directory. If None, the one set in gloabal_prams is used
    n_jobs : int
    safe : bool
        if True, will not overwrite existing data
    """
    # update existing SSV IDs  # TODO: currently this requires a new mapping dict Unclear what to
    #  do in order to enable updates on existing SSD (e.g. after adding new SSVs)
    # paths = glob.glob(ssd.path + "/so_storage/*/*/*/")
    # ssd._ssv_ids = np.array([int(os.path.basename(p.strip("/")))
    #                           for p in paths], dtype=np.uint)
    if target_wd is None:
        target_wd = global_params.config.working_dir
    scaling = ssvs[0].scaling
    new_ssd = SuperSegmentationDataset(working_dir=target_wd, version=new_version,
                                       scaling=scaling)
    for old_ssv in ssvs:
        new_ssv = SuperSegmentationObject(old_ssv.id, version=new_version,
                                          working_dir=target_wd, sv_ids=old_ssv.sv_ids,
                                          scaling=old_ssv.scaling)
        old_ssv.copy2dir(dest_dir=new_ssv.ssv_dir, safe=safe)
    log_reps.info("Saving dataset deep.")
    new_ssd.save_dataset_deep(new_mapping=False, nb_cpus=n_jobs)


def create_sso_skeletons_thread(args):
    from ..proc.graphs import create_graph_from_coords
    from ..reps.rep_helper import surface_samples
    from ..handler.multiviews import generate_rendering_locs

    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]

    ssd = SuperSegmentationDataset(working_dir=working_dir, version=version,
                                   version_dict=version_dict)

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)
        if not global_params.config.allow_skel_gen:
            # TODO: change to create_sso_skeleton_fast as soon as RAG edges
            #  only connected spatially close SVs
            create_sso_skeleton(ssv)
        else:
            # TODO: refactor together with `gen_skel_from_sample_locs`
            verts = ssv.mesh[1].reshape(-1, 3)
            # choose random subset of surface
            np.random.seed(0)
            ixs = np.arange(len(verts))
            np.random.shuffle(ixs)
            ixs = ixs[:int(0.5*len(ixs))]
            if global_params.config.use_new_renderings_locs:
                locs = generate_rendering_locs(verts[ixs], 1000)
            else:
                locs = surface_samples(verts[ixs], bin_sizes=(1000, 1000, 1000),
                                       max_nb_samples=10000, r=500)
            g = create_graph_from_coords(locs, mst=True)
            if g.number_of_edges() == 1:
                edge_list = np.array(list(g.edges()))
            else:
                edge_list = np.array(g.edges())
            del g
            if edge_list.ndim != 2:
                raise ValueError("Edgelist must be a 2D array. Currently: {}\n{}".format(
                    edge_list.ndim, edge_list))
            ssv.skeleton = dict()
            ssv.skeleton["nodes"] = locs / np.array(ssv.scaling)
            ssv.skeleton["edges"] = edge_list
            ssv.skeleton["diameters"] = np.ones(len(locs))
            ssv.save_skeleton()
            # ssv.load_skeleton()  # this will create skeleton from sample locations (edges might go out of the process)
        if ssv.skeleton is None or len(ssv.skeleton["nodes"]) == 0:
            continue
        ssv.save_skeleton()


def preproc_sso_skelfeature_thread(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]

    ssd = SuperSegmentationDataset(working_dir, version, version_dict)

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)
        ssv.load_skeleton()
        if ssv.skeleton is None or len(ssv.skeleton["nodes"]) <= 1:
            log_reps.warning("Skeleton of SSV %d has zero nodes." % ssv_id)
            continue
        for feat_ctx_nm in [500, 1000, 2000, 4000, 8000]:
            try:
                _ = ssv.skel_features(feat_ctx_nm)
            except IndexError as e:
                log_reps.error("Error at SSO %d (context: %d).\n%s" % (
                               ssv.id, feat_ctx_nm, e))


def map_ssv_semseg(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    kwargs_semseg2mesh = args[4]
    global_params.wd = working_dir

    ssd = SuperSegmentationDataset(working_dir=working_dir, version=version,
                                   version_dict=version_dict)

    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)
        ssv.semseg2mesh(**kwargs_semseg2mesh)


def exctract_ssv_morphology_embedding(args):
    ssv_obj_ids = args[0]
    version = args[1]
    version_dict = args[2]
    working_dir = args[3]
    pred_key_appendix = args[4]
    global_params.wd = working_dir

    ssd = SuperSegmentationDataset(working_dir=working_dir, version=version,
                                   version_dict=version_dict)
    from ..handler.prediction import get_tripletnet_model_e3
    for ssv_id in ssv_obj_ids:
        ssv = ssd.get_super_segmentation_object(ssv_id)
        ssv.nb_cpus = global_params.NCORES_PER_NODE // 2  # TODO should be global_params.NGPU_PER_NODE
        m = get_tripletnet_model_e3()
        ssv.predict_views_embedding(m, pred_key_appendix)

