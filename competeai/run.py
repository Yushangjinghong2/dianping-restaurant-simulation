# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""
    Pipeline for running the simulation.
"""
from competeai.simul import Simulation
from competeai.utils import analysis, aggregate

import os
import yaml
import argparse

# parse the argument
parser = argparse.ArgumentParser()
parser.add_argument('name', type=str)
parser.add_argument(
    '--config',
    default=os.path.join('competeai', 'examples', 'group_v2.yaml'),
    help='Path to the simulation YAML config',
)
args = parser.parse_args()

# create a log folder
log_path = f"./logs/{args.name}"

if not os.path.exists(log_path):
    os.makedirs(log_path)
    os.makedirs(f"{log_path}/fig")

relationship_path = os.path.join('competeai', 'relationship.yaml')

with open(relationship_path, 'r') as f:
    relationship = yaml.safe_load(f)

with open(args.config, 'r', encoding='utf-8') as f:
    config = yaml.safe_load(f)
    config['exp_name'] = args.name
    config['relationship'] = relationship
    Simul = Simulation.from_config(config)
    Simul.run()
    





