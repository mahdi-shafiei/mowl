import sys
sys.path.append("../../")
sys.path.append("../")
import mowl
mowl.init_jvm("10g")
from mowl.base_models.elmodel import EmbeddingELModel
from mowl.utils.random import seed_everything
from org.semanticweb.owlapi.model.parameters import Imports
from org.semanticweb.owlapi.model import AxiomType as Ax
from evaluators import PPIEvaluator, SubsumptionFromPPIEvaluator
from datasets import PPIDataset, PPIDatasetV2
from tqdm import tqdm
from mowl.nn import BoxSquaredELModule
import torch as th
import torch.nn as nn
from torch.utils.data import DataLoader
import torch.nn.functional as F
from itertools import cycle
import logging
import math
import click as ck
import os
import wandb
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

th.autograd.set_detect_anomaly(True)

@ck.command()
@ck.option("--dataset_name", "-ds", type=ck.Choice(["ppi_yeast", "ppi_yeast_slim"]), default="ppi_yeast_slim")
@ck.option("--evaluator_name", "-ev", default="ppi", help="Evaluator to use")
@ck.option("--embed_dim", "-dim", default=50, help="Embedding dimension")
@ck.option("--batch_size", "-bs", default=300000, help="Batch size")
@ck.option("--module_margin", "-mm", default=0.1, help="Margin for the module")
@ck.option("--loss_margin", "-lm", default=0.1, help="Margin for the loss function")
@ck.option("--learning_rate", "-lr", default=0.001, help="Learning rate")
@ck.option("--epochs", "-e", default=4000, help="Number of epochs")
@ck.option("--evaluate_every", "-every", default=50, help="Evaluate every n epochs")
@ck.option("--device", "-d", default="cuda", help="Device to use")
@ck.option("--wandb_description", "-desc", default="default")
@ck.option("--no_sweep", "-ns", is_flag=True)
@ck.option("--only_test", "-ot", is_flag=True)
def main(dataset_name, evaluator_name, embed_dim, batch_size,
         module_margin, loss_margin, learning_rate, epochs,
         evaluate_every, device, wandb_description, no_sweep,
         only_test):

    seed_everything(42)
    
    wandb_logger = wandb.init(entity="zhapacfp_team", project="ontoem", group=f"ppi", name=wandb_description)

    if no_sweep:
        wandb_logger.log({"dataset_name": dataset_name,
                          "embed_dim": embed_dim,
                          "module_margin": module_margin,
                          "loss_margin": loss_margin,
                          "learning_rate": learning_rate
                          })
    else:
        dataset_name = wandb.config.dataset_name
        embed_dim = wandb.config.embed_dim
        module_margin = wandb.config.module_margin
        loss_margin = wandb.config.loss_margin
        learning_rate = wandb.config.learning_rate

        
    
    root_dir, dataset = dataset_resolver(dataset_name)

    model_dir = f"{root_dir}/../models/"
    os.makedirs(model_dir, exist_ok=True)

    model_filepath = f"{model_dir}/{embed_dim}_{batch_size}_{module_margin}_{loss_margin}_{learning_rate}.pt"
    model = GeometricELModel(evaluator_name, dataset, batch_size,
                             embed_dim, module_margin, loss_margin,
                             learning_rate, model_filepath,
                             epochs, evaluate_every, device, wandb_logger)

    
    if not only_test:
        model.train()
        
    metrics = model.test()
    print_as_md(metrics)

             
    wandb_logger.log(metrics)
        

def print_as_md(overall_metrics):
    
    metrics = ["test_mr", "test_mrr", "test_auc", "test_hits@1", "test_hits@3", "test_hits@10", "test_hits@50", "test_hits@100"]
    filt_metrics = [k.replace("_", "_f_") for k in metrics]

    string_metrics = "| Property | MR | MRR | AUC | Hits@1 | Hits@3 | Hits@10 | Hits@50 | Hits@100 | \n"
    string_metrics += "| --- | --- | --- | --- | --- | --- | --- | --- | --- | \n"
    string_filtered_metrics = "| Property | MR | MRR | AUC | Hits@1 | Hits@3 | Hits@10 | Hits@50 | Hits@100 | \n"
    string_filtered_metrics += "| --- | --- | --- | --- | --- | --- | --- | --- | --- | \n"
    
    string_metrics += "| Overall | "
    string_filtered_metrics += "| Overall | "
    for metric in metrics:
        if metric == "test_mr":
            string_metrics += f"{int(overall_metrics[metric])} | "
        else:
            string_metrics += f"{overall_metrics[metric]:.4f} | "
    for metric in filt_metrics:
        if metric == "test_f_mr":
            string_filtered_metrics += f"{int(overall_metrics[metric])} | "
        else:
            string_filtered_metrics += f"{overall_metrics[metric]:.4f} | "


    print(string_metrics)
    print("\n\n")
    print(string_filtered_metrics)
        
    

    
def dataset_resolver(dataset_name):
    if dataset_name.lower() == "ppi_yeast":
        root_dir = "../use_cases/ppi_yeast/data/"
    elif dataset_name.lower() == "ppi_yeast_slim":
        root_dir = "../use_cases/ppi_yeast_slim/data/"
    else:
        raise ValueError(f"Dataset {dataset_name} not found")

    return root_dir, PPIDatasetV2(root_dir)

def evaluator_resolver(evaluator_name, *args, **kwargs):
    if evaluator_name.lower() == "ppi":
        return PPIEvaluator(*args, **kwargs)
    elif evaluator_name.lower() == "subsumption":
        return SubsumptionFromPPIEvaluator(*args,
                                           batch_size = 64,
                                           evaluate_with_deductive_closure=True,
                                           **kwargs)
    else:
        raise ValueError(f"Evaluator {evaluator_name} not found")


class GeometricELModel(EmbeddingELModel):
    def __init__(self, evaluator_name, dataset,
                 batch_size, embed_dim, module_margin, loss_margin,
                 learning_rate, model_filepath, epochs,
                 evaluate_every, device, wandb_logger):
        super().__init__(dataset, embed_dim, batch_size, model_filepath=model_filepath)

        self.module = BoxSquaredELModule(len(self.dataset.classes),
                                 len(self.dataset.object_properties),
                                 len(self.dataset.individuals),
                                 self.embed_dim,
                                 module_margin)

        self.evaluator = evaluator_resolver(evaluator_name, dataset, device)
        self.learning_rate = learning_rate
        self.epochs = epochs
        self.evaluate_every = evaluate_every
        self.loss_margin = loss_margin
        self.device = device
        self.wandb_logger = wandb_logger


            
    def train(self):

        dls = {gci_name: DataLoader(ds, batch_size=self.batch_size, shuffle=True)
               for gci_name, ds in self.training_datasets.items() if len(ds) > 0}
        dls_sizes = {gci_name: len(ds) for gci_name, ds in self.training_datasets.items() if len(ds) > 0}
        total_dls_size = sum(dls_sizes.values())
        dls_weights = {gci_name: ds_size/total_dls_size for gci_name, ds_size in dls_sizes.items()}

        main_dl = dls["gci2"]
        logger.info(f"Training with {len(main_dl)} batches of size {self.batch_size}")
        dls = {gci_name: cycle(dl) for gci_name, dl in dls.items() if gci_name != "gci2"}
        logger.info(f"Dataloaders: {dls_sizes}")

        tolerance = 5
        curr_tolerance = tolerance

        optimizer = th.optim.Adam(self.module.parameters(), lr=self.learning_rate)

        best_mrr = 0
        best_loss = float("inf")
        
        num_classes = len(self.dataset.classes)
        all_classes = self.dataset.classes.as_str
        all_classes_to_idx = {c: i for i, c in enumerate(all_classes)}
        protein_classes = self.dataset.evaluation_classes[0].as_str
        protein_ids = [all_classes_to_idx[c] for c in protein_classes]
        protein_ids = th.tensor(protein_ids, device=self.device)
        
        self.module = self.module.to(self.device)
        for epoch in tqdm(range(self.epochs)):
            self.module.train()
            

            total_train_loss = 0

            loss = 0
            for batch_data in main_dl:

                batch_data = batch_data.to(self.device)
                pos_logits = self.module(batch_data, "gci2").mean()
                neg_idxs = th.randint(0, len(protein_ids), (len(batch_data),), device=self.device)
                neg_idxs = protein_ids[neg_idxs]
                neg_batch = th.cat([batch_data[:, :-1], neg_idxs.unsqueeze(1)], dim=1)
                # neg_logits = self.module(neg_batch, "gci2").mean()
                neg_logits = self.module(neg_batch, "gci2", neg=True).mean()
                loss += pos_logits + neg_logits
                # loss = - F.logsigmoid(-pos_logits + neg_logits - self.loss_margin).mean() * dls_weights["gci2"]

                for gci_name, gci_dl in dls.items():
                    if gci_name == "gci2":
                        continue

                    batch_data = next(gci_dl).to(self.device)
                    pos_logits = self.module(batch_data, gci_name).mean()
                    # neg_idxs = th.randint(0, num_classes, (len(batch_data),), device=self.device)
                    # neg_batch = th.cat([batch_data[:, :-1], neg_idxs.unsqueeze(1)], dim=1)
                    # neg_logits = self.module(neg_batch, gci_name)
                    # loss += - F.logsigmoid(-pos_logits + neg_logits - self.loss_margin).mean() * dls_weights[gci_name]
                    loss += pos_logits

                loss += self.module.regularization_loss()
                                                
                optimizer.zero_grad()
                loss.backward()
                optimizer.step()
                
                
                total_train_loss += loss.item()
                                    
            if epoch % self.evaluate_every == 0:
                valid_metrics = self.evaluator.evaluate(self.module, mode="valid")
                valid_mrr = valid_metrics["valid_mrr"]
                valid_mr = valid_metrics["valid_mr"]
                valid_metrics["train_loss"] = total_train_loss
                                    
                self.wandb_logger.log(valid_metrics)

                if valid_mrr > best_mrr:
                    best_mrr = valid_mrr
                    curr_tolerance = tolerance
                    th.save(self.module.state_dict(), self.model_filepath)
                else:
                    curr_tolerance -= 1

                if curr_tolerance == 0:
                    logger.info(f"Early stopping at epoch {epoch}")
                    break

                logger.info(f"Epoch {epoch} - Train Loss: {total_train_loss:4f}  - Valid MRR: {valid_mrr:4f} - Valid MR: {valid_mr:4f}")

    def test(self):
        self.module.load_state_dict(th.load(self.model_filepath))
        self.module.to(self.device)
        self.module.eval()
        
        return self.evaluator.evaluate(self.module)


    def test_by_property(self):
        self.module.load_state_dict(th.load(self.model_filepath))
        self.module.to(self.device)
        self.module.eval()
        return self.evaluator.evaluate_by_property(self.module)


class DummyLogger():
    def __init__(self, *args, **kwargs):
        pass

    def log(self, *args, **kwargs):
        pass
    
if __name__ == "__main__":
    main()
