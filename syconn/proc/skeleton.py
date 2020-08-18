from typing import Optional, Union

import numpy as np
import tqdm
from scipy import ndimage
import kimimaro
import networkx as nx
import cloudvolume
from knossos_utils.skeleton import Skeleton, SkeletonAnnotation, SkeletonNode
from syconn.extraction.block_processing_C import relabel_vol_nonexist2zero
from syconn.reps.super_segmentation import SuperSegmentationDataset
from syconn.handler.basics import load_pkl2obj, kd_factory
from syconn import global_params


def kimimaro_skelgen(cube_size, cube_offset, nb_cpus: Optional[int] = None,
                     ds: Optional[np.ndarray] = None) -> dict:
    """
    code from https://pypi.org/project/kimimaro/

    Args:
        cube_size: size of processed cube in mag 1 voxels.
        cube_offset: starting point of cubes (in mag 1 voxel coordinates)
        nb_cpus: Number of cpus used by kimimaro.
        ds: Downsampling.

    Returns:
        Skeleton with nodes, edges in physical parameters

    """
    if nb_cpus is None:
        nb_cpus = 1

    ssd = SuperSegmentationDataset(working_dir=global_params.config.working_dir)
    kd = kd_factory(global_params.config.kd_seg_path)
    # TODO: uint32 conversion should be controlled externally
    seg = kd.load_seg(size=cube_size, offset=cube_offset, mag=1).swapaxes(0, 2).astype(np.uint32)
    if ds is not None:
        seg = ndimage.zoom(seg, 1 / ds, order=0)
    else:
        ds = np.ones(3)
    # transform IDs to agglomerated SVs
    relabel_vol_nonexist2zero(seg, ssd.mapping_dict_reversed)

    # kimimaro code
    skels = kimimaro.skeletonize(
        seg,
        teasar_params={
            'scale': 2,
            'const': 500,  # physical units
            'pdrf_exponent': 4,
            'pdrf_scale': 100000,
            'soma_detection_threshold': 1100,  # physical units
            'soma_acceptance_threshold': 3500,  # physical units
            'soma_invalidation_scale': 1.0,
            'soma_invalidation_const': 2000,  # physical units
            'max_paths': 100,  # default None
        },
        # object_ids=[ ... ], # process only the specified labels
        # extra_targets_before=[ (27,33,100), (44,45,46) ], # target points in voxels
        # extra_targets_after=[ (27,33,100), (44,45,46) ], # target points in voxels
        dust_threshold=1000,  # skip connected components with fewer than this many voxels
        anisotropy=kd.scales[0] * ds,  # index 1 is mag 2
        fix_branching=True,  # default True
        fix_borders=True,  # default True
        fill_holes=True,
        progress=False,  # show progress bar
        parallel=nb_cpus,  # <= 0 all cpu, 1 single process, 2+ multiprocess
    )
    for ii in skels:
        # cell.vertices already in physical coordinates (nm)
        # now add the offset in physical coordinates
        skels[ii].downsample(10)
        skels[ii] = sparsify_skelcv(skels[ii])
        skels[ii].vertices += (cube_offset * kd.scales[0]).astype(np.int)
        # cloud_volume docu: " reduce size of skeleton by factor of 2, preserves branch and end
        # points" link:https://github.com/seung-lab/cloud-volume/wiki/Advanced-Topic:-Skeleton
    return skels


def kimimaro_mergeskels(path_list, cell_id):
    """
    For debugging. Load files and merge dictionaries.

    Args:
        path_list: list of paths to locations for partial skeletons generated by kimimaro
        cell_id: ssv.ids

    Returns: merged skeletons with nodes in physical parameters

    """
    skel_list = []
    for f in path_list:
        part_dict = load_pkl2obj(f)
        # part_dict is now a defaultdict(list)
        skel_list.extend(part_dict[int(cell_id)])
    # merge skeletons to one connected component
    # a set of skeletons produced from the same label id
    skel = cloudvolume.PrecomputedSkeleton.simple_merge(skel_list).consolidate()
    skel = kimimaro.postprocess(
        skel,
        dust_threshold=500,  # physical units
        tick_threshold=1000  # physical units
    )
    # Split input skeletons into connected components and
    # then join the two nearest vertices within `radius` distance
    # of each other until there is only a single connected component
    # or no pairs of points nearer than `radius` exist.
    # Fuse all remaining components into a single skeleton.
    skel = kimimaro.join_close_components(skel, radius=None)  # no threshold
    return skel


def kimimaro_skels_tokzip(cell_skel, cell_id, zipname):
    # write to zip file
    skel = Skeleton()
    anno = SkeletonAnnotation()
    # anno.scaling = global_params.config['scaling']
    node_mapping = {}
    cv = cell_skel.vertices
    pbar = tqdm.tqdm(total=len(cv) + len(cell_skel.edges))
    for i, v in enumerate(cv):
        n = SkeletonNode().from_scratch(anno, int((v[0])+54000), int((v[1]) + 59000),
                                        int((v[2]) + 3000*20))
        # above only for example_cube with certain offset
        # n = SkeletonNode().from_scratch(anno, int(c[0] / 10), int(c[1] / 10), int(c[2] / 20) )
        # pdb.set_trace()
        node_mapping[i] = n
        anno.addNode(n)
        pbar.update(1)
    for e in cell_skel.edges:
        anno.addEdge(node_mapping[e[0]], node_mapping[e[1]])
        pbar.update(1)
    skel.add_annotation(anno)
    skel.to_kzip('%s/kzip_%.i.k.zip' % (zipname, cell_id), force_overwrite=True)


def skelcv2nxgraph(skel: cloudvolume.Skeleton) -> nx.Graph:
    """
    Transform skeleton (cloud volume) to networkx graph with node attributes 'position' and 'radius' taken from
    skel.vertices and skel.radii respectively.

    Args:
        skel:

    Returns:

    """
    g = nx.Graph()
    g.add_nodes_from([(ix, dict(position=coord, radius=skel.radii[ix])) for ix, coord in enumerate(skel.vertices)])
    g.add_edges_from(skel.edges)
    return g


def nxgraph2skelcv(g: nx.Graph) -> cloudvolume.Skeleton:
    # transform networkx node IDs (non-consecutive) into a consecutive ID space
    old2new_ixs = dict()
    for ii, n in enumerate(g.nodes()):
        old2new_ixs[n] = ii
    edges = np.array(g.edges, dtype=np.int)
    for ii in range(edges.shape[0]):
        e1, e2 = edges[ii]
        edges[ii] = (old2new_ixs[e1], old2new_ixs[e2])
    skel = cloudvolume.Skeleton(np.array([g.node[ix]['position'] for ix in g.nodes()], dtype=np.float32),
                                edges, np.array([g.node[ix]['radius'] for ix in g.nodes()], dtype=np.float32))
    return skel


def sparsify_skelcv(skel: cloudvolume.Skeleton, scale: Optional[np.ndarray] = None,
                    angle_thresh: float = 135,
                    max_dist_thresh: Union[int, float] = 500,
                    min_dist_thresh: Union[int, float] = 50) -> nx.Graph:
    """
    Recursively removes nodes in skeleton. Ignores leaf and branch nodes.

    Args:
        skel: networkx graph of the sso skeleton. Requires 'position' attribute.
        scale: Scale factor; equal to the physical voxel size (nm).
        angle_thresh: Only remove nodes for which the angle between their adjacent edges is > angle_thresh (in degree).
        max_dist_thresh: Maximum distance desired between every node.
        min_dist_thresh: Minimum distance desired between every node.

    Returns: sso containing the sparse skeleton.

    """
    # TODO: this could be refactored to improve performance and readability..
    skel_nx = skelcv2nxgraph(skel)
    if scale is None:
        scale = global_params.config['scaling']
    change = 1
    while change > 0:
        change = 0
        visiting_nodes = list({k for k, v in dict(skel_nx.degree()).items() if v == 2})
        for visiting_node in visiting_nodes:
            neighbours = [n for n in skel_nx.neighbors(visiting_node)]
            if skel_nx.degree(visiting_node) == 2:
                left_node = neighbours[0]
                right_node = neighbours[1]
                vector_left_node = np.array(
                    [int(skel_nx.node[left_node]['position'][ix]) - int(skel_nx.node[visiting_node]['position'][ix]) for
                     ix in range(3)]) * scale
                vector_right_node = np.array([int(skel_nx.node[right_node]['position'][ix]) -
                                              int(skel_nx.node[visiting_node]['position'][ix]) for ix in
                                              range(3)]) * scale

                dot_prod = np.dot(vector_left_node / np.linalg.norm(vector_left_node),
                                  vector_right_node / np.linalg.norm(vector_right_node))
                angle = np.arccos(dot_prod) * 180 / np.pi
                dist = np.linalg.norm([int(skel_nx.node[right_node]['position'][ix] * scale[ix]) - int(
                    skel_nx.node[left_node]['position'][ix] * scale[ix]) for ix in range(3)])

                if (abs(angle) > angle_thresh and dist < max_dist_thresh) or dist <= min_dist_thresh:
                    skel_nx.remove_node(visiting_node)
                    skel_nx.add_edge(left_node, right_node)
                    change += 1
    return nxgraph2skelcv(skel_nx)
