import mowl
from mowl.datasets import PathDataset
from mowl.datasets.builtin import PPIYeastSlimDataset
from mowl.datasets.base import OWLClasses

class SubsumptionDataset(PathDataset):
    def __init__(self, root_dir):
        super().__init__(root_dir + "train.owl", root_dir + "valid.owl", root_dir + "test.owl")

        self.root_dir = root_dir
        self._deductive_closure_ontology = None
        
    @property
    def deductive_closure_ontology(self):
        if self._deductive_closure_ontology is None:
            self._deductive_closure_ontology = PathDataset(self.root_dir + "train_deductive_closure.owl").ontology

        return self._deductive_closure_ontology

    @property
    def evaluation_classes(self):
        if self._evaluation_classes is None:
            classes = self.ontology.getClassesInSignature()
            classes = OWLClasses(classes)
            self._evaluation_classes = classes, classes

        return self._evaluation_classes
