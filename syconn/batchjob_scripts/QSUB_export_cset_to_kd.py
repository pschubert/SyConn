# -*- coding: utf-8 -*-
# SyConn - Synaptic connectivity inference toolkit
#
# Copyright (c) 2016 - now
# Max Planck Institute of Neurobiology, Martinsried, Germany
# Authors: Philipp Schubert, Jörgen Kornfeld

import sys
import warnings
warnings.filterwarnings("ignore", message=".*You are using implicit channel selection.*")
warnings.filterwarnings("ignore", message=".*You are initializing a KnossosDataset from a path.*")
warnings.filterwarnings("ignore", message=".*dataset.value has been deprecated.*")  # h5py deprecation warning
try:
    import cPickle as pkl
except Exception:
    import pickle as pkl
from knossos_utils.chunky import _export_cset_as_kd_thread

path_storage_file = sys.argv[1]
path_out_file = sys.argv[2]

with open(path_storage_file, 'rb') as f:
    args = []
    while True:
        try:
            args.append(pkl.load(f))
        except EOFError:
            break

coords = args[0]
params = args[1:]
for coord in coords:
    _export_cset_as_kd_thread([coord, ] + params)

with open(path_out_file, "wb") as f:
    pkl.dump(None, f)
