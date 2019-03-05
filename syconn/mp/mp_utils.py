# -*- coding: utf-8 -*-
# SyConn - Synaptic connectivity inference toolkit
#
# Copyright (c) 2016 - now
# Max-Planck-Institute of Neurobiology, Munich, Germany
# Authors: Philipp Schubert, Sven Dorkenwald, Jörgen Kornfeld

try:
    import cPickle as pkl
except ImportError:
    import pickle as pkl
import getpass
from multiprocessing import cpu_count, Process
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import multiprocessing.pool
import os
import shutil
import subprocess
import sys
import time
import tqdm
from . import log_mp

MyPool = multiprocessing.Pool
# if not (sys.version_info[0] == 3 and sys.version_info[1] > 5):
#     # found NoDaemonProcess on stackexchange by Chris Arndt - enables
#     # hierarchical multiprocessing
#     class NoDaemonProcess(Process):
#         # make 'daemon' attribute always return False
#         def _get_daemon(self):
#             return False
#
#         def _set_daemon(self, value):
#             pass
#
#         daemon = property(_get_daemon, _set_daemon)
#
#
#     # We sub-class multi_proc.pool.Pool instead of multi_proc.Pool
#     # because the latter is only a wrapper function, not a proper class.
#     class MyPool(multiprocessing.pool.Pool):
#         Process = NoDaemonProcess
# else:
#     class NoDaemonProcess(multiprocessing.Process):
#         @property
#         def daemon(self):
#             return False
#
#         @daemon.setter
#         def daemon(self, value):
#             pass
#
#     class NoDaemonContext(type(multiprocessing.get_context())):
#         Process = NoDaemonProcess
#
#     # We sub-class multiprocessing.pool.Pool instead of multiprocessing.Pool
#     # because the latter is only a wrapper function, not a proper class.
#     class MyPool(multiprocessing.pool.Pool):
#         def __init__(self, *args, **kwargs):
#             kwargs['context'] = NoDaemonContext()
#             super(MyPool, self).__init__(*args, **kwargs)


def parallel_process(array, function, n_jobs, use_kwargs=False, front_num=0):
    """From http://danshiebler.com/2016-09-14-parallel-progress-bar/
        A parallel version of the map function with a progress bar.

        Args:
            array (array-like): An array to iterate over.
            function (function): A python function to apply to the elements of array
            n_jobs (int, default=16): The number of cores to use
            use_kwargs (boolean, default=False): Whether to consider the elements of array as dictionaries of
                keyword arguments to function
            front_num (int, default=3): The number of iterations to run serially before kicking off the parallel job.
                Useful for catching bugs
        Returns:
            [function(array[0]), function(array[1]), ...]
    """
    #We run the first few iterations serially to catch bugs
    if front_num > 0:
        front = [function(**a) if use_kwargs else function(a) for a in array[:front_num]]
    else:
        front = []
    #Assemble the workers
    with ProcessPoolExecutor(max_workers=n_jobs) as pool:
        #Pass the elements of array into function
        if use_kwargs:
            futures = [pool.submit(function, **a) for a in array[front_num:]]
        else:
            futures = [pool.submit(function, a) for a in array[front_num:]]
        kwargs = {
            'total': len(futures),
            'unit': 'job',
            'unit_scale': True,
            'leave': False,
            'ncols': 80,
            'dynamic_ncols': False
        }
        #Print out the progress as tasks complete
        for f in tqdm.tqdm(as_completed(futures), **kwargs):
            pass
    out = []
    #Get the results from the futures.
    for i, future in enumerate(futures):
        try:
            out.append(future.result())
        except Exception as e:
            out.append(e)
    return front + out


def start_multiprocess(func, params, debug=False, verbose=False, nb_cpus=None):
    """

    Parameters
    ----------
    func : function
    params : function parameters
    debug : boolean
    verbose : bool
    nb_cpus : int

    Returns
    -------
    result: list
        list of function returns
    """
    if nb_cpus is None:
        nb_cpus = cpu_count()

    if debug:
        nb_cpus = 1

    nb_cpus = min(nb_cpus, len(params), cpu_count())

    if verbose:
        log_mp.debug("Computing %d parameters with %d cpus." % (len(params), nb_cpus))

    start = time.time()
    if nb_cpus > 1:
        pool = MyPool(nb_cpus)
        result = pool.map(func, params)
        pool.close()
        pool.join()
    else:
        result = list(map(func, params))

    if verbose:
        log_mp.debug("Time to compute: {:.1f} min".format((time.time() - start) / 60.))

    return result


def start_multiprocess_imap(func, params, debug=False, verbose=False,
                            nb_cpus=None, show_progress=True):
    """
    Multiprocessing method which supports progress bar (therefore using
    imap instead of map). # TODO: support generator params

    Parameters
    ----------
    func : function
    params : Iterable
        function parameters
    debug : boolean
    verbose : bool
    nb_cpus : int
    show_progress : bool

    Returns
    -------
    result: list
        list of function returns
    """
    if nb_cpus is None:
        nb_cpus = cpu_count()

    nb_cpus = min(nb_cpus, len(params), cpu_count())

    if debug:
        nb_cpus = 1

    if verbose:
        log_mp.debug("Computing %d parameters with %d cpus." % (len(params), nb_cpus))

    start = time.time()
    if nb_cpus > 1:
        with MyPool(nb_cpus) as pool:
            if show_progress:
                result = parallel_process(params, func, nb_cpus)
                print(len(params))
                print("showing progress")
                # # comparable speed but less continuous pbar updates
                # result = list(tqdm.tqdm(pool.imap(func, params), total=len(params),
                #                         ncols=80, leave=True, unit='jobs',
                #                         unit_scale=True, dynamic_ncols=False))
            else:
                result = list(pool.map(func, params))
        print(len(params))
        print("hahaha")

    else:
        print(len(params))
        print("kakaka")
        if show_progress:
            pbar = tqdm.tqdm(total=len(params), ncols=80, leave=False,
                             unit='job', unit_scale=True, dynamic_ncols=False)
            result = []
            for p in params:
                result.append(func(p))
                pbar.update(1)
            pbar.close()
        else:
            result = []
            for p in params:
                result.append(func(p))
        print(len(params))
        print("kakaka")

    if verbose:
        log_mp.debug("Time to compute: {:.1f} min".format((time.time() - start) / 60.))

    return result


def start_multiprocess_obj(func_name, params, debug=False, verbose=False,
                           nb_cpus=None):
    """

    Parameters
    ----------
    func_name : str
    params : List[List]
        each element in params must be object with attribute func_name
        (+ optional: kwargs)
    debug : boolean
    verbose : bool
    nb_cpus : int

    Returns
    -------
    result: List
        list of function returns
    """
    if nb_cpus is None:
        nb_cpus = cpu_count()

    if debug:
        nb_cpus = 1

    nb_cpus = min(nb_cpus, len(params), cpu_count())

    if verbose:
        log_mp.debug("Computing %d parameters with %d cpus." % (len(params), nb_cpus))
    for el in params:
        el.insert(0, func_name)
    start = time.time()
    if nb_cpus > 1:
        pool = MyPool(nb_cpus)
        result = pool.map(multi_helper_obj, params)
        pool.close()
        pool.join()
    else:
        result = list(map(multi_helper_obj, params))
    if verbose:
        log_mp.debug("Time to compute: {:.1f} min".format((time.time() - start) / 60.))
    return result


def multi_helper_obj(args):
    """
    Generic helper emthod for multiprocessed jobs. Calls the given object
    method.

    Parameters
    ----------
    args : iterable
        object, method name, optional: kwargs

    Returns
    -------

    """
    attr_str = args[0]
    obj = args[1]
    if len(args) == 3:
        kwargs = args[2]
    else:
        kwargs = {}
    attr = getattr(obj, attr_str)
    # check if attr is callable, i.e. a method to be called
    if not hasattr(attr, '__call__'):
        return attr
    return attr(**kwargs)
