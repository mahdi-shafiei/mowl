import os
import tempfile

from java.io import File
from org.semanticweb.owlapi.apibinding import OWLManager
from org.semanticweb.owlapi.formats import OWLXMLDocumentFormat
from java.io import FileOutputStream
from mowl.graph.graph import GraphGenModel
from mowl.graph.edge import Edge


import mowl.graph.owl2vec_star.Onto_Projection as o2v


class OWL2VecParser(GraphGenModel):
    
    def __init__(self, dataset, bidirectional_taxonomy):
        super().__init__(dataset)
        self.bidirectional_taxonomy = bidirectional_taxonomy
        
    def parse(self):

        '''
        Performs the ontology parsing.

        :returns: A list of triples where each triple is of the form :math:`(head, relation, tail)`
        :rtype: List of :class:`mowl.graph.edge.Edge`
        '''

        path = "temp.owl"
        man = OWLManager.createOWLOntologyManager()
        fileout = File(path)
        man.saveOntology(self.dataset, OWLXMLDocumentFormat(), FileOutputStream(fileout))
    
        parser = o2v.OntologyProjection(path, bidirectional_taxonomy = self.bidirectional_taxonomy, include_literals=False)

        os.remove(path)

        parser.extractProjection()

        graph = parser.getProjectionGraph()

        edges = []

        for s, r, d in graph:
            edges.append(Edge(str(s), str(r), str(d)))
    

        return edges
