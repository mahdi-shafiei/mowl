#!/usr/bin/env python

import click as ck
import numpy as np
import pandas as pd
import pickle
import gzip
import os
import sys
import logging

sys.path.insert(0, '')

from datasets import PPIYeastDataset
from onto2vec.model import Onto2Vec


@ck.command()
def main():
    ds = PPIYeastDataset()
    model = Onto2Vec(ds)
    model.train()


if __name__ == '__main__':
    main()
