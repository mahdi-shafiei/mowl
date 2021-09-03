import pandas as pd
import dgl
from dgl import nn as dglnn
import torch as th
import numpy as np
from torch import nn
from torch.nn import functional as F
from torch import optim
from sklearn.metrics import roc_curve, auc, matthews_corrcoef
from torch.utils.data import DataLoader, IterableDataset
from dgl.nn.pytorch import RelGraphConv
import random
from ray import tune


class GNNSim(Model):
    def __init__(self,
                 n_hidden,
                 dropout,
                 learning_rate,
                 num_bases,
                 batch_size,
                 epochs,
                 graph_generation_method = "taxonomy", #Default: generate graph taxonomy
                 file_params = None #Dictionary of data file paths corresponding to the graph generation method (NEEDS REFACTORING)
                 ):
        self.n_hidden = n_hidden
        self.dropout = dropout
        self.learning_rate = learning_rate
        self.num_bases = num_bases
        self.batch_size = batch_size
        self.epochs = epochs
        self.graph_generation_method = graph_generation_method
        self.file_params = file_params



    def train(n_hid, dropout, lr, num_bases, batch_size, epochs, file_params, checkpoint_dir = None, tuning= False):

        g, annots, prot_idx = load_graph_data(file_params)
    
        print(f"Num nodes: {g.number_of_nodes()}")
    
        num_rels = len(g.canonical_etypes)

        g = dgl.to_homogeneous(g)

        num_nodes = g.number_of_nodes()
    
        feat_dim = 2
        loss_func = nn.BCELoss()

        train_df, val_df, _ = load_data(file_params)

        model = PPIModel(feat_dim, num_rels, num_bases, num_nodes, n_hid, dropout)

        device = "cpu"
        if th.cuda.is_available():
            device = "cuda:0"
            if th.cuda.device_count() > 1:
                model = nn.DataParallel(model)
            
        annots = th.FloatTensor(annots).to(device)


        model.to(device)
        optimizer = optim.Adam(model.parameters(), lr=lr)

        if checkpoint_dir:
            model_state, optimizer_state = torch.load(
                os.path.join(checkpoint_dir, "checkpoint"))
            model.load_state_dict(model_state)
            optimizer.load_state_dict(optimizer_state)

        train_labels = th.FloatTensor(train_df['labels'].values).to(device)
        val_labels = th.FloatTensor(val_df['labels'].values).to(device)
    
        train_data = GraphDataset(g, train_df, train_labels, annots, prot_idx)
        val_data = GraphDataset(g, val_df, val_labels, annots, prot_idx)
    
        train_set_batches = get_batches(train_data, batch_size)
        val_set_batches = get_batches(val_data, batch_size)
    
        best_roc_auc = 0

        epochs = 2
        for epoch in range(epochs):
            epoch_loss = 0
            model.train()

            with ck.progressbar(train_set_batches) as bar:
                for iter, (batch_g, batch_feat, batch_labels) in enumerate(bar):
                    logits = model(batch_g.to(device), batch_feat)

                    labels = batch_labels.unsqueeze(1).to(device)
                    loss = loss_func(logits, labels)
                    optimizer.zero_grad()
                    loss.backward()
                    optimizer.step()
                    epoch_loss += loss.detach().item()

                epoch_loss /= (iter+1)

        
            model.eval()
            val_loss = 0
            preds = []
            labels = []
            with th.no_grad():
                optimizer.zero_grad()
                with ck.progressbar(val_set_batches) as bar:
                    for iter, (batch_g, batch_feat, batch_labels) in enumerate(bar):
                        
                        logits = model(batch_g.to(device), batch_feat)
                        lbls = batch_labels.unsqueeze(1).to(device)
                        loss = loss_func(logits, lbls)
                        val_loss += loss.detach().item()
                        labels = np.append(labels, lbls.cpu())
                        preds = np.append(preds, logits.cpu())
                    val_loss /= (iter+1)

            roc_auc = compute_roc(labels, preds)
            if not tuning:
                if roc_auc > best_roc_auc:
                    best_roc_auc = roc_auc
                    th.save(model.state_dict(), curr_path + '/data/model_rel.pt')
                print(f'Epoch {epoch}: Loss - {epoch_loss}, \tVal loss - {val_loss}, \tAUC - {roc_auc}')

                if tuning:
                    with tune.checkpoint_dir(epoch) as checkpoint_dir:
                        path = os.path.join(checkpoint_dir, "checkpoint")
                        th.save((model.state_dict(), optimizer.state_dict()), path)

                    tune.report(loss=(val_loss), auc=roc_auc)
        print("Finished Training")



    def evaluate(n_hid, dropout, num_bases, batch_size, file_params, model=None):

        device = "cpu"
        g, annots, prot_idx = load_graph_data(file_params)
    
        num_nodes = g.number_of_nodes()
        print(f"Num nodes: {g.number_of_nodes()}")
    
        annots = th.FloatTensor(annots).to(device)
        num_rels = len(g.canonical_etypes)

        g = dgl.to_homogeneous(g)

        feat_dim = 2
        loss_func = nn.BCELoss()


        _,_, test_df = load_data(file_params)
        test_labels = th.FloatTensor(test_df['labels'].values).to(device)
    
        test_data = GraphDataset(g, test_df, test_labels, annots, prot_idx)
    
        test_set_batches = get_batches(test_data, batch_size)

        if model == None:
            model = PPIModel(feat_dim, num_rels, num_bases, num_nodes, n_hid, dropout)
            model.load_state_dict(th.load('data/model_rel.pt'))
        model.to(device)
        model.eval()
        test_loss = 0

        preds = []
        with th.no_grad():
            with ck.progressbar(test_set_batches) as bar:
                for iter, (batch_g, batch_feat, batch_labels) in enumerate(bar):
                    logits = model(batch_g.to(device), batch_feat)
                    labels = batch_labels.unsqueeze(1).to(device)
                    loss = loss_func(logits, labels)
                    test_loss += loss.detach().item()
                    preds = np.append(preds, logits.cpu())
                test_loss /= (iter+1)

        labels = test_df['labels'].values
        roc_auc = compute_roc(labels, preds)
        print(f'Test loss - {test_loss}, \tAUC - {roc_auc}')

        return test_loss, roc_auc






        
    def load_data(self):
         train_df, test_df = load_ppi_data()
    
         split = int(len(test_df) * 0.5)
         index = np.arange(len(test_df))
         val_df = test_df.iloc[index[split:]]
         test_df = test_df.iloc[index[:split]]
         
         return train_df, val_df, test_df



    class RGCN(BaseRGCN):

         def build_hidden_layer(self, idx):
             act = F.relu if idx < self.num_hidden_layers - 1 else None
             return RelGraphConv(self.h_dim, self.h_dim, self.num_rels, "basis",
                self.num_bases, activation=act, self_loop=True,
                dropout=self.dropout)

         
    class PPIModel(nn.Module):

        def __init__(self, h_dim, num_rels, num_bases, num_nodes, n_hid, dropout):
            super().__init__()
        
            self.h_dim = h_dim
            self.num_rels = num_rels
            self.num_bases = None if num_bases < 0 else num_bases
            self.num_nodes = num_nodes

            print(f"Num rels: {self.num_rels}")
            print(f"Num bases: {self.num_bases}")

            self.rgcn = RGCN(self.h_dim, 
                        self.h_dim, 
                        self.h_dim, 
                        self.num_rels, 
                        self.num_bases,
                        num_hidden_layers=n_hid, 
                        dropout=dropout,
                        use_self_loop=False, 
                        use_cuda=True
                        )
        

            self.fc = nn.Linear(self.num_nodes*self.h_dim, 1) 
        
        def forward(self, g, features):
            edge_type = g.edata[dgl.ETYPE].long()

            x = self.rgcn(g, features, edge_type, None)

            x = th.flatten(x).view(-1, self.num_nodes*self.h_dim)
            return th.sigmoid(self.fc(x))
        


    class GraphDataset(IterableDataset):

        def __init__(self, graph, df, labels, annots, prot_idx):
            self.graph = graph
            self.annots = annots
            self.labels = labels
            self.df = df
            self.prot_idx = prot_idx
        
            def get_data(self):
                for i, row in enumerate(self.df.itertuples()):
                    p1, p2 = row.interactions
                    label = self.labels[i].view(1, 1)
                    if p1 not in self.prot_idx or p2 not in self.prot_idx:
                        continue
                    pi1, pi2 = self.prot_idx[p1], self.prot_idx[p2]
           
                    feat = self.annots[:, [pi1, pi2]]

                    yield (self.graph, feat, label)

        def __iter__(self):
            return self.get_data()

        def __len__(self):
            return len(self.df)


    def load_ppi_data(file_params):
        train_df = pd.read_pickle(file_params["train_inter_file"])
        index = np.arange(len(train_df))
        np.random.seed(seed=0)
        np.random.shuffle(index)
        train_df = train_df.iloc[index[:1000]]
        
        test_df = pd.read_pickle(file_params["test_inter_file"])
        index = np.arange(len(test_df))
        np.random.seed(seed=0)
        np.random.shuffle(index)
        test_df = test_df.iloc[index[:2000]]
        return train_df, test_df

    def load_graph_data(self, file_params):

        parser = gen_factory(self.graph_generation_method)
        g = parser.parse(format='dgl')
        
        graphs, data_dict = dgl.load_graphs(graph_file)
        g = graphs[0]

        num_nodes = g.number_of_nodes()

        #g = dgl.add_self_loop(g, 'id')

        with open(nodes_file, "rb") as pkl_file:
            node_idx = pkl.load(pkl_file)
    
            
        df = pd.read_pickle(data_file)
        df = df[df['orgs'] == '559292']
  

        annotations = np.zeros((num_nodes, len(df)), dtype=np.float32)

        prot_idx = {}
        for i, row in enumerate(df.itertuples()):
            prot_id = row.accessions.split(';')[0]
            prot_idx[prot_id] = i
            for go_id in row.prop_annotations:
                if go_id in node_idx:   
                    annotations[node_idx[go_id], i] = 1
        return g, annotations, prot_idx
    
