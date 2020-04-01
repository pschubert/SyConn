# ELEKTRONN3 - Neural Network Toolkit
#
# Copyright (c) 2019 - now
# Max Planck Institute of Neurobiology, Munich, Germany
# Authors: Philipp Schubert
from syconn.cnn.TrainData import CellCloudData

import os
import torch
import argparse
import random
import numpy as np
# Don't move this stuff, it needs to be run this early to work
import elektronn3
elektronn3.select_mpl_backend('Agg')
import morphx.processing.clouds as clouds
from torch import nn
from elektronn3.models.convpoint import ModelNet40, ModelNetBig, ModelNetAttention, \
    ModelNetSelection, ModelNetSelectionBig, ModelNetAttentionBig, ModelNet40xConv
from elektronn3.training import Trainer3d, Backup, metrics
try:
    from torch.optim.lr_scheduler import CosineAnnealingWarmRestarts
except ModuleNotFoundError as e:
    print(e)
    from elektronn3.training.schedulers import CosineAnnealingWarmRestarts

# PARSE PARAMETERS #
parser = argparse.ArgumentParser(description='Train a network.')
parser.add_argument('--na', type=str, help='Experiment name',
                    default=None)
parser.add_argument('--sr', type=str, help='Save root', default=None)
parser.add_argument('--bs', type=int, default=16, help='Batch size')
parser.add_argument('--sp', type=int, default=40000, help='Number of sample points')
parser.add_argument('--scale_norm', type=int, default=30000, help='Scale factor for normalization')
parser.add_argument('--co', action='store_true', help='Disable CUDA')
parser.add_argument('--seed', default=0, help='Random seed')
parser.add_argument(
    '-j', '--jit', metavar='MODE', default='disabled',  # TODO: does not work
    choices=['disabled', 'train', 'onsave'],
    help="""Options:
"disabled": Completely disable JIT tracing;
"onsave": Use regular Python model for training, but trace it on-demand for saving training state;
"train": Use traced model for training and serialize it on disk"""
)
parser.add_argument('--cval', default=None, help='Cross-validation split indicator.')


args = parser.parse_args()

# SET UP ENVIRONMENT #

random_seed = args.seed
torch.manual_seed(random_seed)
np.random.seed(random_seed)
random.seed(random_seed)

# define parameters
use_cuda = not args.co
name = args.na
batch_size = args.bs
npoints = args.sp
scale_norm = args.scale_norm
save_root = args.sr
cval = args.cval

if cval is None:
    cval = 0

lr = 1e-3
lr_stepsize = 1000
lr_dec = 0.995
max_steps = 100000

# celltype specific
eval_nr = 0  # number of repetition per cval
cellshape_only = False
use_syntype = True
dr = 0.3
track_running_stats = False
use_bn = False
num_classes = 8
onehot = True

if name is None:
    name = f'celltype_pts_scale{scale_norm}_nb{npoints}'
    if cellshape_only:
        name += '_cellshapeOnly'
    if not use_syntype:
        name += '_noSyntype'
if onehot:
    input_channels = 5 if use_syntype else 4
else:
    input_channels = 1
    name += '_flatinp'
if not use_bn:
    name += '_noBN'
if track_running_stats:
    name += '_trackRunStats'

if use_cuda:
    device = torch.device('cuda')
else:
    device = torch.device('cpu')

print(f'Running on device: {device}')

# set paths
if save_root is None:
    save_root = '~/e3_training_convpoint/'
save_root = os.path.expanduser(save_root)

# CREATE NETWORK AND PREPARE DATA SET

# Model selection
model = ModelNet40(input_channels, num_classes, dropout=dr, use_bn=use_bn,
                   track_running_stats=track_running_stats)
name += '_moreAug4'
# model = ModelNetBig(input_channels, num_classes, dropout=dr)
# name += '_big'

# model = ModelNetAttention(input_channels, num_classes, npoints=npoints, dropout=dr)
# name += '_attention'
#
# model = ModelNetAttentionBig(input_channels, num_classes, npoints=npoints,
#                              dropout=dr)
# name += '_attention_big_2'


# model = ModelNetSelection(input_channels, num_classes, npoints=npoints, dropout=dr)
# name += '_selection'

# model = ModelNetSelectionBig(input_channels, num_classes, dropout=dr)
# name += '_selection_big'

name += f'_CV{cval}_eval{eval_nr}'
model = nn.DataParallel(model)

if use_cuda:
    model.to(device)

example_input = (torch.ones(batch_size, npoints, input_channels).to(device),
                 torch.ones(batch_size, npoints, 3).to(device))
enable_save_trace = False if args.jit == 'disabled' else True
if args.jit == 'onsave':
    # Make sure that tracing works
    tracedmodel = torch.jit.trace(model, example_input)
elif args.jit == 'train':
    if getattr(model, 'checkpointing', False):
        raise NotImplementedError(
            'Traced models with checkpointing currently don\'t '
            'work, so either run with --disable-trace or disable '
            'checkpointing.')
    tracedmodel = torch.jit.trace(model, example_input)
    model = tracedmodel

# Transformations to be applied to samples before feeding them to the network
train_transform = clouds.Compose([clouds.RandomVariation((-50, 50), distr='normal'),  # in nm
                                  clouds.Normalization(scale_norm),
                                  clouds.Center(),
                                  clouds.RandomRotate(apply_flip=True),
                                  clouds.RandomScale(distr_scale=0.05, distr='normal')])
valid_transform = clouds.Compose([clouds.Normalization(scale_norm),
                                  clouds.Center()])

train_ds = CellCloudData(npoints=npoints, transform=train_transform, cv_val=cval,
                         cellshape_only=cellshape_only, use_syntype=use_syntype,
                         onehot=onehot, batch_size=batch_size)
valid_ds = CellCloudData(npoints=npoints, transform=valid_transform, train=False,
                         cv_val=cval, cellshape_only=cellshape_only,
                         use_syntype=use_syntype, onehot=onehot, batch_size=batch_size)

# PREPARE AND START TRAINING #

# set up optimization
optimizer = torch.optim.Adam(model.parameters(), lr=lr)

# optimizer = torch.optim.SGD(
#     model.parameters(),
#     lr=lr,  # Learning rate is set by the lr_sched below
#     momentum=0.9,
#     weight_decay=0.5e-5,
# )

# optimizer = SWA(optimizer)  # Enable support for Stochastic Weight Averaging
# lr_sched = torch.optim.lr_scheduler.StepLR(optimizer, lr_stepsize, lr_dec)
lr_sched = torch.optim.lr_scheduler.ExponentialLR(optimizer, gamma=0.99992)
# lr_sched = CosineAnnealingWarmRestarts(optimizer, T_0=5000, T_mult=2)
# lr_sched = torch.optim.lr_scheduler.CyclicLR(
#     optimizer,
#     base_lr=1e-4,
#     max_lr=1e-2,
#     step_size_up=2000,
#     cycle_momentum=True,
#     mode='exp_range',
#     gamma=0.99994,
# )
criterion = torch.nn.CrossEntropyLoss()
if use_cuda:
    criterion.cuda()

valid_metrics = {  # mean metrics
    'val_accuracy_mean': metrics.Accuracy(),
    'val_precision_mean': metrics.Precision(),
    'val_recall_mean': metrics.Recall(),
    'val_DSC_mean': metrics.DSC(),
    'val_IoU_mean': metrics.IoU(),
}

# Create trainer
# it seems pytorch 1.1 does not support batch_size=None to enable batched dataloader, instead
# using batch size 1 with custom callte_fn
trainer = Trainer3d(
    model=model,
    criterion=criterion,
    optimizer=optimizer,
    device=device,
    train_dataset=train_ds,
    valid_dataset=valid_ds,
    batchsize=1,
    num_workers=10,
    valid_metrics=valid_metrics,
    save_root=save_root,
    enable_save_trace=enable_save_trace,
    exp_name=name,
    schedulers={"lr": lr_sched},
    num_classes=num_classes,
    # example_input=example_input,
    dataloader_kwargs=dict(collate_fn=lambda x: x[0])
)

# Archiving training script, src folder, env info
bk = Backup(script_path=__file__,
            save_path=trainer.save_path).archive_backup()

# Start training
trainer.run(max_steps)