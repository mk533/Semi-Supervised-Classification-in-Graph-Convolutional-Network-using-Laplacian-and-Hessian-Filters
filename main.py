# -*- coding: utf-8 -*-
"""Thesis_code.ipynb

Automatically generated by Colaboratory.

Original file is located at
    https://colab.research.google.com/drive/1Oic8MvTCFMa_1GR_I7UJNdGvEHp7-r4D
"""





from __future__ import division
from __future__ import print_function

import time
import argparse
import numpy as np

import torch
import pandas as pd
import torch.nn.functional as F
import torch.optim as optim
import torch.nn as nn
import scipy.sparse as sp
import scipy.linalg as la
import sys
import pickle as pkl
import networkx as nx
import math

import torch

from torch.nn.parameter import Parameter
from torch.nn.modules.module import Module



class GraphConvolution(Module):
    """
    Simple GCN layer, similar to https://arxiv.org/abs/1609.02907
    """

    def __init__(self, in_features, out_features, bias=True):
        super(GraphConvolution, self).__init__()
        self.in_features = in_features
        self.out_features = out_features
        self.weight = Parameter(torch.FloatTensor(in_features, out_features))
        if bias:
            self.bias = Parameter(torch.FloatTensor(out_features))
        else:
            self.register_parameter('bias', None)
        self.reset_parameters()

    def reset_parameters(self):
        stdv = 1. / math.sqrt(self.weight.size(1))
        self.weight.data.uniform_(-stdv, stdv)
        if self.bias is not None:
            self.bias.data.uniform_(-stdv, stdv)

    def forward(self, input, adj):
        support = torch.mm(input, self.weight)
        output = torch.spmm(adj, support)
        if self.bias is not None:
            return output + self.bias
        else:
            return output

    def __repr__(self):
        return self.__class__.__name__ + ' (' \
               + str(self.in_features) + ' -> ' \
               + str(self.out_features) + ')'


def accuracy(output, labels):
    preds = output.max(1)[1].type_as(labels)
    correct = preds.eq(labels).double()
    correct = correct.sum()
    return correct / len(labels)

def sample_mask(idx, l):
    """Create mask."""
    mask = np.zeros(l)
    mask[idx] = 1
    return np.array(mask, dtype=np.bool)

def parse_index_file(filename):
    """Parse index file."""
    index = []
    for line in open(filename):
        index.append(int(line.strip()))
    return index

def sparse_mx_to_torch_sparse_tensor(sparse_mx):
    """Convert a scipy sparse matrix to a torch sparse tensor."""
    sparse_mx = sparse_mx.tocoo().astype(np.float32)
    indices = torch.from_numpy(
        np.vstack((sparse_mx.row, sparse_mx.col)).astype(np.int64))
    values = torch.from_numpy(sparse_mx.data)
    shape = torch.Size(sparse_mx.shape)
    return torch.sparse.FloatTensor(indices, values, shape)


def normalize_adj(adj):
    """Symmetrically normalize adjacency matrix."""
    adj = sp.coo_matrix(adj)
    rowsum = np.array(adj.sum(1))
    d_inv_sqrt = np.power(rowsum, -0.5).flatten()
    d_inv_sqrt[np.isinf(d_inv_sqrt)] = 0.
    d_mat_inv_sqrt = sp.diags(d_inv_sqrt)
    return adj.dot(d_mat_inv_sqrt).transpose().dot(d_mat_inv_sqrt).tocoo()


def preprocess_adj(adj):
    """Preprocessing of adjacency matrix for simple GCN model and conversion to tuple representation."""
    adj_normalized = normalize_adj(adj + sp.eye(adj.shape[0]))
    return adj_normalized



def encode_onehot(labels):
    classes = set(labels)
    classes_dict = {c: np.identity(len(classes))[i, :] for i, c in
                    enumerate(classes)}
    labels_onehot = np.array(list(map(classes_dict.get, labels)),
                             dtype=np.int32)
    return labels_onehot

def normalize(mx):
    """Row-normalize sparse matrix"""
    rowsum = np.array(mx.sum(1))
    r_inv = np.power(rowsum, -1).flatten()
    r_inv[np.isinf(r_inv)] = 0.
    r_mat_inv = sp.diags(r_inv)
    mx = r_mat_inv.dot(mx)
    return mx

def load_data(dataset_str):
    """
    Loads input data from gcn/data directory

    ind.dataset_str.x => the feature vectors of the training instances as scipy.sparse.csr.csr_matrix object;
    ind.dataset_str.tx => the feature vectors of the test instances as scipy.sparse.csr.csr_matrix object;
    ind.dataset_str.allx => the feature vectors of both labeled and unlabeled training instances
        (a superset of ind.dataset_str.x) as scipy.sparse.csr.csr_matrix object;
    ind.dataset_str.y => the one-hot labels of the labeled training instances as numpy.ndarray object;
    ind.dataset_str.ty => the one-hot labels of the test instances as numpy.ndarray object;
    ind.dataset_str.ally => the labels for instances in ind.dataset_str.allx as numpy.ndarray object;
    ind.dataset_str.graph => a dict in the format {index: [index_of_neighbor_nodes]} as collections.defaultdict
        object;
    ind.dataset_str.test.index => the indices of test instances in graph, for the inductive setting as list object.

    All objects above must be saved using python pickle module.

    :param dataset_str: Dataset name
    :return: All data input files loaded (as well the training/test data).
    """
    names = ['x', 'y', 'tx', 'ty', 'allx', 'ally', 'graph']
    objects = []
    for i in range(len(names)):
        with open("data/ind.{}.{}".format(dataset_str, names[i]), 'rb') as f:
            if sys.version_info > (3, 0):
                objects.append(pkl.load(f, encoding='latin1'))
            else:
                objects.append(pkl.load(f))

    x, y, tx, ty, allx, ally, graph = tuple(objects)
    #print("x",x,"y",y,"tx",tx,"ty",ty,"allx",allx,"ally",ally,"graph",graph)
    test_idx_reorder = parse_index_file("data/ind.{}.test.index".format(dataset_str))
    test_idx_range = np.sort(test_idx_reorder)

    if dataset_str == 'citeseer':
        # Fix citeseer dataset (there are some isolated nodes in the graph)
        # Find isolated nodes, add them as zero-vecs into the right position
        test_idx_range_full = range(min(test_idx_reorder), max(test_idx_reorder)+1)
        tx_extended = sp.lil_matrix((len(test_idx_range_full), x.shape[1]))
        tx_extended[test_idx_range-min(test_idx_range), :] = tx
        tx = tx_extended
        ty_extended = np.zeros((len(test_idx_range_full), y.shape[1]))
        ty_extended[test_idx_range-min(test_idx_range), :] = ty
        ty = ty_extended

    features = sp.vstack((allx, tx)).tolil()
    features[test_idx_reorder, :] = features[test_idx_range, :]
    adj = nx.adjacency_matrix(nx.from_dict_of_lists(graph))

    labels = np.vstack((ally, ty))
    labels[test_idx_reorder, :] = labels[test_idx_range, :]

    idx_test = test_idx_range.tolist()
    idx_train = range(len(y))
    idx_val = range(len(y), len(y)+500)

    train_mask = sample_mask(idx_train, labels.shape[0])
    val_mask = sample_mask(idx_val, labels.shape[0])
    test_mask = sample_mask(idx_test, labels.shape[0])

    y_train = np.zeros(labels.shape)
    y_val = np.zeros(labels.shape)
    y_test = np.zeros(labels.shape)
    y_train[train_mask, :] = labels[train_mask, :]
    y_val[val_mask, :] = labels[val_mask, :]
    y_test[test_mask, :] = labels[test_mask, :]

    print("------88****************-----------")
    # for i in features:
    #     print(i)
    print(adj.shape,features.shape,labels.shape)

    idx_train = range(140)
    idx_val = range(200, 500)
    idx_test = range(500, 1500)

    adj = preprocess_adj(adj)
    features = normalize(features)

    features = torch.FloatTensor(np.array(features.todense()))
    labels = torch.LongTensor(np.where(labels)[1])
    adj = sparse_mx_to_torch_sparse_tensor(adj)


    return adj, features, labels, idx_train, idx_val, idx_test


class GCN_base(nn.Module):
    def __init__(self, nfeat, nhid, nclass, dropout):
        super(GCN_base, self).__init__()

        self.gc1 = GraphConvolution(nfeat, nhid)
        self.gc2 = GraphConvolution(nhid, nclass)
        self.dropout = dropout

    def forward(self, x, adj):
        x = F.relu(self.gc1(x, adj))
        x = F.dropout(x, self.dropout, training=self.training)
        x = self.gc2(x, adj)
        return F.log_softmax(x, dim=1)
        #return x

## LAPLACIAN MODEL WITH ONE HIDDEN LAYER , DROPOUT AND RELU IS USED
##-----------------------------------------------------
class GCN_Lap(nn.Module):
    def __init__(self, nfeat, nhid, nclass, dropout):
        super(GCN_Lap, self).__init__()
        print("In Laplace")
        self.gc1 = GraphConvolution(nfeat, nhid)
        self.gc2 = GraphConvolution(nhid, nhid)
        #self.gc3 = GraphConvolution(nhid, nclass)
        self.dropout = dropout

    def forward(self, x, adj):
        x = F.relu(self.gc1(x, adj))
        x = F.dropout(x, self.dropout, training=self.training)
        x = self.gc2(x, adj)
        #x = F.relu(self.gc3(x, adj))
        #return F.log_softmax(x, dim=1)
        return x
##-----------------------------------------------------

## HESSIAN MODEL WITH ONE HIDDEN LAYER, DROPOUT AND RELU IS USED
##-----------------------------------------------------

class GCN_Hes(nn.Module):
    def __init__(self, nfeat, nhid, nclass, dropout):
        super(GCN_Hes, self).__init__()
        print("In Hessian")
        self.gc1 = GraphConvolution(nfeat, nhid)
        self.gc2 = GraphConvolution(nhid, nhid)
        #self.gc2 = GraphConvolution(nhid, nclass)
        self.dropout = dropout

    def forward(self, x, x_Hessian):
        x = F.relu(self.gc1(x, x_Hessian))
        x = F.dropout(x, self.dropout, training=self.training)
        x = self.gc2(x, x_Hessian)
        #x = F.relu(self.gc3(x, adj))
        #return F.log_softmax(x, dim=1)
        return x

##-----------------------------------------------------



## ENSEMBLE  IS MENTIONED BELOW  WE TAKE HIDDEN LAYERS FROM MODEL LAPLACIAN AND MODEL HEASSIAN AND CONCAT THEM
##-----------------------------------------------------
class GCN_Ensemble(nn.Module):
    def __init__(self, modelA, modelB):
        super(GCN_Ensemble, self).__init__()
        self.modelA = modelA
        self.modelB = modelB
        self.classifier = nn.Linear(32, 6)
        print("In Ensemble")

    def forward(self, x, adj, x_Hessian):
        x1 = self.modelA(x, adj)           #FROM LAPLCIAN MODEL
        x2 = self.modelB(x, x_Hessian)     #FROM HESSIAN MODEL
        x = torch.cat((x1, x2), dim=1)     # CONCATING STEP
        #x = self.classifier(F.relu(x))
        x = F.log_softmax(x, dim=1)        #SOFTMAX
        return x
##-----------------------------------------------------



parser = argparse.ArgumentParser()
parser.add_argument('--no-cuda', action='store_true', default=False,
                    help='Disables CUDA training.')
parser.add_argument('--fastmode', action='store_true', default=False,
                    help='Validate during training pass.')
parser.add_argument('--seed', type=int, default=23, help='Random seed.')
parser.add_argument('--epochs', type=int, default=500,
                    help='Number of epochs to train.')
parser.add_argument('--lr', type=float, default=0.005,
                    help='Initial learning rate.')
parser.add_argument('--weight_decay', type=float, default=4e-5,
                    help='Weight decay (L2 loss on parameters).')
parser.add_argument('--hidden', type=int, default=16,
                    help='Number of hidden units.')
parser.add_argument('--dropout', type=float, default=0.5,
                    help='Dropout rate (1 - keep probability).')
args = parser.parse_args(args=[])

args.cuda = not args.no_cuda and torch.cuda.is_available()

np.random.seed(args.seed)
torch.manual_seed(args.seed)
if args.cuda:
    torch.cuda.manual_seed(args.seed)

adj, features, labels, idx_train, idx_val, idx_test = load_data("cora")



A = pd.read_csv('data/cora_hessian.csv',header=None) # READING HESSIAN MATRIX THAT IS DERIVED FROM MATLAB CODE
#A=A.cuda()
# chunks = pd.read_csv('pubmed_hessian.csv', chunksize=500,header=None)
# A = pd.concat(chunks)
# import cudf
# A = cudf.DataFrame.from_pandas(A)

adj_hessian = A.values
# adj_hessian = adj_hessian.cuda()
print(type(adj_hessian))

# if torch.cuda.is_available():
#   device = torch.device('cuda:0')
# else:
#   device = torch.device('cpu') # don't have GPU

# device

#adj_hessian = torch.from_numpy(adj_hessian).float().to(device)
# adj_hessian = torch.tensor(adj_hessian, dtype =torch.float32).to(device)

# !pip install scikit-cuda

#eigvals, eigvecs = torch.tensor(la.eig(adj_hessian) ).to(device)

eigvals, eigvecs = la.eig(A)     ## GETTING EIGEN VALUES FOR HESSIAN MATRIX
eigvals = np.asarray(eigvals)
lam = (max(eigvals))   # TAKING MAXIMUM EIGEN VALUE FROM EIGEN VALUES

adj_hessian = (2/lam)*adj_hessian     ### Hes = (2/LAM)Hes - IN*LAM IS CALCULATED. AND SPARESE MATRIX IS FORMED

adj_hessian = sp.csr_matrix(adj_hessian)

adj_hessian = adj_hessian - sp.eye(adj.shape[0])

x_Hessian = sparse_mx_to_torch_sparse_tensor(adj_hessian)

modelA = GCN_Lap(nfeat=features.shape[1],   
            nhid=args.hidden,
            nclass=labels.max().item() + 1,
            dropout=args.dropout)     ## LAPLACIAN MODEL IS DEFINED


modelB = GCN_Hes(nfeat=features.shape[1],
            nhid=args.hidden,
            nclass=labels.max().item() + 1,
            dropout=args.dropout)   ## HESSIAN MODEL IS DEFINED

model = GCN_Ensemble(modelA, modelB)
# model = GCN_base(nfeat=features.shape[1],
#             nhid=args.hidden,
#             nclass=labels.max().item() + 1,
#             dropout=args.dropout)
optimizer = optim.Adam(model.parameters(),
                       lr=args.lr, weight_decay=args.weight_decay)  ## WE USE BOTH MODELS AND SEND TO ENSEMBLE
print("--->")
if args.cuda:
  print(args.cuda)
  model.cuda()
  features = features.cuda()
  adj = adj.cuda()
  labels = labels.cuda()
  # idx_train = idx_train.cuda()
  # idx_val = idx_val.cuda()
  # idx_test = idx_test.cuda()
  x_Hessian = x_Hessian.cuda()

def train(epoch):
    t = time.time()
    model.train()
    optimizer.zero_grad()
    output = model(features, adj, x_Hessian)
    #print("train1----->",output.shape)
    #output = model(features, adj)
    loss_train = F.nll_loss(output[idx_train], labels[idx_train])
    acc_train = accuracy(output[idx_train], labels[idx_train])
    loss_train.backward()
    optimizer.step()

    if not args.fastmode:
        # Evaluate validation set performance separately,
        # deactivates dropout during validation run.
        model.eval()
        output = model(features, adj, x_Hessian)
        #print("train2----->",output.shape)
        #output = model(features, adj)

    loss_val = F.nll_loss(output[idx_val], labels[idx_val])
    acc_val = accuracy(output[idx_val], labels[idx_val])
    print('Epoch: {:04d}'.format(epoch+1),
          'loss_train: {:.4f}'.format(loss_train.item()),
          'acc_train: {:.4f}'.format(acc_train.item()),
          'loss_val: {:.4f}'.format(loss_val.item()),
          'acc_val: {:.4f}'.format(acc_val.item()),
          'time: {:.4f}s'.format(time.time() - t))


def test():
    model.eval()
    output = model(features, adj, x_Hessian)
    #print("test----->",output.shape)
    #output = model(features, adj)
    loss_test = F.nll_loss(output[idx_test], labels[idx_test])
    acc_test = accuracy(output[idx_test], labels[idx_test])
    print("Test set results:",
          "loss= {:.4f}".format(loss_test.item()),
          "accuracy= {:.4f}".format(acc_test.item()))


# Train model
t_total = time.time()
for epoch in range(args.epochs):
    train(epoch)
print("Optimization Finished!")
print("Total time elapsed: {:.4f}s".format(time.time() - t_total))

test()

