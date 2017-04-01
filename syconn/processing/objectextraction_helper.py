# -*- coding: utf-8 -*-
# SyConn - Synaptic connectivity inference toolkit
#
# Copyright (c) 2016 - now
# Max-Planck-Institute for Medical Research, Heidelberg, Germany
# Authors: Sven Dorkenwald, Philipp Schubert, Jörgen Kornfeld
import cPickle as pkl
import glob
import h5py
import numpy as np
import os
from scipy import ndimage
import time

from ..utils import datahandler, basics#, segmentationdataset
from knossos_utils import chunky, knossosdataset
from syconnfs.representations import segmentation


def extract_ids_thread(args):
    chunk = args[0]
    filename = args[1]
    hdf5names = args[2]

    ids = {}

    path = chunk.folder + filename + ".h5"
    this_segmentation = datahandler.load_from_h5py(path, hdf5names,
                                                   as_dict=True)
    for hdf5_name in hdf5names:
        ids[hdf5_name] = np.unique(this_segmentation[hdf5_name])

    return [chunk.number, ids]


def validate_chunks_thread(args):
    chunk = args[0]
    filename = args[1]
    hdf5names = args[2]

    path = chunk.folder + filename + ".h5"
    if os.path.exists(path):
        path = chunk.folder + filename + ".h5"
        try:
            this_segmentation = datahandler.load_from_h5py(path, hdf5names,
                                                           as_dict=True)
            for hdf5name in hdf5names:
                if np.sum(this_segmentation[hdf5name]) == 0:
                    with open(chunk.folder + "/errors_%s.txt" % filename, "a") as f:
                        f.write("zero error @ %s" % hdf5name)
        except:
            with open(chunk.folder + "/errors_%s.txt" % filename, "a") as f:
                f.write("load error")
    else:
        with open(chunk.folder + "/errors_%s.txt" % filename, "a") as f:
            f.write("existence error")


def validate_knossos_cubes_thread(args):
    cset_path = args[0]
    filename = args[1]
    hdf5names = args[2]
    coord_start = args[3]
    stride = args[4]

    cset = chunky.load_dataset(cset_path, update_paths=True)

    coords = []
    for x in range(0, cset.box_size[0], 128):
        for y in range(0, cset.box_size[1], 128):
            for z in range(0, cset.box_size[2], 128):
                coords.append([x, y, z])

    for coord in coords[coord_start: coord_start + stride]:
        cube = cset.from_chunky_to_matrix([128, 128, 128], coord, filename,
                                          hdf5names)
        for hdf5name in hdf5names:
            if np.sum(cube[hdf5name]) == 0:
                with open(cset.path_head_folder + "/errors_%s_%d_%d_%d.txt" %
                        (filename, coord[0], coord[1], coord[2]), "w") as f:
                    f.write("zero error @ %s" % hdf5name)


def gauss_threshold_connected_components_thread(args):
    chunk = args[0]
    path_head_folder = args[1]
    filename = args[2]
    hdf5names = args[3]
    overlap = args[4]
    sigmas = args[5]
    thresholds = args[6]
    swapdata = args[7]
    membrane_filename = args[8]
    membrane_kd_path = args[9]
    hdf5_name_membrane = args[10]
    fast_load = args[11]
    suffix = args[12]

    box_offset = np.array(chunk.coordinates) - np.array(overlap)
    size = np.array(chunk.size) + 2*np.array(overlap)

    if swapdata:
        size = basics.switch_array_entries(size, [0, 2])

    if not fast_load:
        cset = chunky.load_dataset(path_head_folder)
        bin_data_dict = cset.from_chunky_to_matrix(size, box_offset,
                                                   filename, hdf5names)
    else:
        bin_data_dict = datahandler.load_from_h5py(chunk.folder + filename + ".h5",
                                                   hdf5names, as_dict=True)

    labels_data = []
    nb_cc_list = []
    for nb_hdf5_name in range(len(hdf5names)):
        hdf5_name = hdf5names[nb_hdf5_name]
        tmp_data = np.copy(bin_data_dict[hdf5_name])

        tmp_data_shape = tmp_data.shape
        offset = (np.array(tmp_data_shape) - np.array(chunk.size) -
                  2 * np.array(overlap)) / 2
        offset = offset.astype(np.int)
        if np.any(offset < 0):
            offset = np.array([0, 0, 0])
        tmp_data = tmp_data[offset[0]: tmp_data_shape[0]-offset[0],
                            offset[1]: tmp_data_shape[1]-offset[1],
                            offset[2]: tmp_data_shape[2]-offset[2]]

        if np.sum(sigmas[nb_hdf5_name]) != 0:
            tmp_data = \
                ndimage.gaussian_filter(tmp_data, sigmas[nb_hdf5_name])

        if hdf5_name in ["vc", "vc"] and membrane_filename is not None and \
                        hdf5_name_membrane is not None:
            membrane_data = datahandler.load_from_h5py(chunk.folder+membrane_filename+".h5",
                                                       hdf5_name_membrane)[0]
            membrane_data_shape = membrane_data.shape
            offset = (np.array(membrane_data_shape) - np.array(tmp_data.shape)) / 2
            membrane_data = membrane_data[offset[0]: membrane_data_shape[0]-offset[0],
                                          offset[1]: membrane_data_shape[1]-offset[1],
                                          offset[2]: membrane_data_shape[2]-offset[2]]
            tmp_data[membrane_data > 255*.4] = 0
        elif hdf5_name == ["vc", "vc"] and membrane_kd_path is not None:
            kd_bar = knossosdataset.KnossosDataset()
            kd_bar.initialize_from_knossos_path(membrane_kd_path)
            membrane_data = kd_bar.from_raw_cubes_to_matrix(size, box_offset)
            tmp_data[membrane_data > 255*.4] = 0

        if thresholds[nb_hdf5_name] != 0:
            tmp_data = np.array(tmp_data > thresholds[nb_hdf5_name],
                                dtype=np.uint8)

        this_labels_data, nb_cc = ndimage.label(tmp_data)
        nb_cc_list.append([chunk.number, hdf5_name, nb_cc])
        labels_data.append(this_labels_data)

    datahandler.save_to_h5py(labels_data,
                             chunk.folder + filename +
                             "_connected_components%s.h5" % suffix,
                             hdf5names)

    return nb_cc_list


def make_unique_labels_thread(args):
    chunk = args[0]
    filename = args[1]
    hdf5names = args[2]
    this_max_nb_dict = args[3]
    suffix = args[4]

    cc_data_list = datahandler.load_from_h5py(chunk.folder + filename +
                                              "_connected_components%s.h5"
                                              % suffix, hdf5names)

    for nb_hdf5_name in range(len(hdf5names)):
        hdf5_name = hdf5names[nb_hdf5_name]
        matrix = cc_data_list[nb_hdf5_name]
        matrix[matrix > 0] += this_max_nb_dict[hdf5_name]

    datahandler.save_to_h5py(cc_data_list,
                             chunk.folder + filename +
                             "_unique_components%s.h5"
                             % suffix, hdf5names)


def get_neighbouring_chunks(cset, chunk, chunk_list=None, diagonal=False):
    """ Returns the numbers of all neighbours

    Parameters:
    -----------
    cset: chunkDataset object
    chunk: chunk object

    Returns:
    --------
    list of int
        -1 if neighbour does not exist, else number
         order: [< x, < y, < z, > x, > y, > z]

    """
    coordinate = np.array(chunk.coordinates)
    neighbours = []
    for dim in range(3):
        try:
            this_coordinate = \
                coordinate - \
                datahandler.switch_array_entries(np.array([chunk.size[dim], 0, 0]),
                                        [0, dim])
            neighbour = cset.coord_dict[tuple(this_coordinate)]
            if not chunk_list is None:
                if neighbour in chunk_list:
                    neighbours.append(neighbour)
                else:
                    neighbours.append(-1)
            else:
                neighbours.append(neighbour)
        except:
            neighbours.append(-1)

    for dim in range(3):
        try:
            this_coordinate = \
                coordinate + \
                datahandler.switch_array_entries(np.array([chunk.size[dim], 0, 0]), [0, dim])
            neighbour = cset.coord_dict[tuple(this_coordinate)]
            if not chunk_list is None:
                if neighbour in chunk_list:
                    neighbours.append(neighbour)
                else:
                    neighbours.append(-1)
            else:
                neighbours.append(neighbour)
        except:
            neighbours.append(-1)
    return neighbours


def make_stitch_list_thread(args):
    cset = args[0]
    nb_chunk = args[1]
    filename = args[2]
    hdf5names = args[3]
    stitch_overlap = args[4]
    overlap = args[5]
    suffix = args[6]
    chunk_list = args[7]

    chunk = cset.chunk_dict[nb_chunk]
    cc_data_list = datahandler.load_from_h5py(chunk.folder + filename +
                                     "_unique_components%s.h5"
                                     % suffix, hdf5names)
    neighbours = get_neighbouring_chunks(cset, chunk, chunk_list)

    map_dict = {}
    for nb_hdf5_name in range(len(hdf5names)):
        map_dict[hdf5names[nb_hdf5_name]] = []

    for ii in range(3):
        if neighbours[ii] != -1:
            compare_chunk = cset.chunk_dict[neighbours[ii]]
            cc_data_list_to_compare = \
                datahandler.load_from_h5py(compare_chunk.folder + filename +
                                  "_unique_components%s.h5"
                                  % suffix, hdf5names)

            cc_area = {}
            cc_area_to_compare = {}
            if ii < 3:
                for nb_hdf5_name in range(len(hdf5names)):
                    this_cc_data = cc_data_list[nb_hdf5_name]
                    this_cc_data_to_compare = \
                        cc_data_list_to_compare[nb_hdf5_name]

                    cc_area[nb_hdf5_name] = \
                        datahandler.cut_array_in_one_dim(
                            this_cc_data,
                            overlap[ii] - stitch_overlap[ii],
                            overlap[ii] + stitch_overlap[ii], ii)

                    cc_area_to_compare[nb_hdf5_name] = \
                        datahandler.cut_array_in_one_dim(
                            this_cc_data_to_compare,
                            this_cc_data_to_compare.shape[ii] - overlap[ii] -
                            stitch_overlap[ii],
                            this_cc_data_to_compare.shape[ii] - overlap[ii] +
                            stitch_overlap[ii], ii)

            else:
                id = ii - 3
                for nb_hdf5_name in range(len(hdf5names)):
                    this_cc_data = cc_data_list[nb_hdf5_name]
                    this_cc_data_to_compare = \
                        cc_data_list_to_compare[nb_hdf5_name]

                    cc_area[nb_hdf5_name] = \
                        datahandler.cut_array_in_one_dim(
                            this_cc_data,
                            -overlap[id] - stitch_overlap[id],
                            -overlap[id] + stitch_overlap[id], id)

                    cc_area_to_compare[nb_hdf5_name] = \
                        datahandler.cut_array_in_one_dim(
                            this_cc_data_to_compare,
                            overlap[id] - stitch_overlap[id],
                            overlap[id] + stitch_overlap[id], id)

            for nb_hdf5_name in range(len(hdf5names)):
                this_shape = cc_area[nb_hdf5_name].shape
                for x in range(this_shape[0]):
                    for y in range(this_shape[1]):
                        for z in range(this_shape[2]):

                            hdf5_name = hdf5names[nb_hdf5_name]
                            this_id = cc_area[nb_hdf5_name][x, y, z]
                            compare_id = \
                                cc_area_to_compare[nb_hdf5_name][x, y, z]
                            if this_id != 0:
                                if compare_id != 0:
                                    try:
                                        if map_dict[hdf5_name][-1] != \
                                                (this_id, compare_id):
                                            map_dict[hdf5_name].append(
                                                (this_id, compare_id))
                                    except:
                                        map_dict[hdf5_name].append(
                                            (this_id, compare_id))
    return map_dict


def apply_merge_list_thread(args):
    chunk = args[0]
    filename = args[1]
    hdf5names = args[2]
    merge_list_dict_path = args[3]
    postfix = args[4]

    cc_data_list = datahandler.load_from_h5py(chunk.folder + filename +
                                              "_unique_components%s.h5"
                                              % postfix, hdf5names)

    merge_list_dict = pkl.load(open(merge_list_dict_path))

    for nb_hdf5_name in range(len(hdf5names)):
        hdf5_name = hdf5names[nb_hdf5_name]
        this_cc = cc_data_list[nb_hdf5_name]
        id_changer = merge_list_dict[hdf5_name]
        this_shape = this_cc.shape
        offset = (np.array(this_shape) - chunk.size) / 2
        this_cc = this_cc[offset[0]: this_shape[0] - offset[0],
                          offset[1]: this_shape[1] - offset[1],
                          offset[2]: this_shape[2] - offset[2]]
        this_cc = id_changer[this_cc]
        cc_data_list[nb_hdf5_name] = np.array(this_cc, dtype=np.uint32)

    datahandler.save_to_h5py(cc_data_list,
                             chunk.folder + filename +
                             "_stitched_components%s.h5" % postfix,
                             hdf5names)


def extract_voxels_thread(args):
    chunk = args[0]
    workfolder = args[1]
    filename = args[2]
    hdf5names = args[3]
    suffix = args[4]
    dataset_versions = args[5]

    for nb_hdf5_name in range(len(hdf5names)):
        hdf5_name = hdf5names[nb_hdf5_name]
        segdataset = segmentation.SegmentationDataset(hdf5_name,
                                                      version=dataset_versions[hdf5_name],
                                                      working_dir=workfolder)
        path = chunk.folder + filename + "_stitched_components%s.h5" % suffix

        if not os.path.exists(path):
            path = chunk.folder + filename + ".h5"
        this_segmentation = datahandler.load_from_h5py(path, [hdf5_name])[0]

        unique_ids = np.unique(this_segmentation)
        for unique_id in unique_ids:
            if unique_id == 0:
                continue

            id_mask = this_segmentation == unique_id
            id_mask, in_chunk_offset = basics.crop_bool_array(id_mask)
            abs_offset = chunk.coordinates + np.array(in_chunk_offset)
            abs_offset = abs_offset.astype(np.int)
            segobj = segmentation.SegmentationObject(unique_id, hdf5_name,
                                                     version=segdataset.version,
                                                     working_dir=segdataset.working_dir,
                                                     create=True)
            segobj.save_voxels(id_mask, abs_offset)
            print unique_id
