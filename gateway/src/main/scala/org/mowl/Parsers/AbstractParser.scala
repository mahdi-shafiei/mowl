package org.mowl.Parsers

// OWL API imports
import org.semanticweb.owlapi.model._
import org.semanticweb.owlapi.apibinding.OWLManager
import org.semanticweb.owlapi.model.parameters.Imports


import collection.JavaConverters._
import collection.mutable._

import org.mowl.Types._


trait AbstractParser{

  def ontology: OWLOntology

  val ontManager = OWLManager.createOWLOntologyManager()
  val dataFactory = ontManager.getOWLDataFactory()

  def parse = {
    val imports = Imports.fromBoolean(false)

    val goClasses = ontology.getClassesInSignature(imports).asScala.toList
    printf("INFO: Number of ontology classes: %d\n", goClasses.length)

    val edges = goClasses.foldLeft(List[Edge]()){(acc, x) => acc ::: processOntClass(x)}

    edges.asJava
  }

  //Abstract methods
  def parseAxiom(ontClass: OWLClass, axiom: OWLClassAxiom): List[Edge]
  //////////////////////

  //Non-abstract methods
  def processOntClass(ontClass: OWLClass): List[Edge] = {
    val axioms = ontology.getAxioms(ontClass).asScala.toList
    val edges = axioms.flatMap(parseAxiom(ontClass, _: OWLClassAxiom))
    edges
  }






}