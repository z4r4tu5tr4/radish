# -*- coding: utf-8 -*-

"""
    This module provides a class to represent a Scenario Outline
"""

from radish.scenario import Scenario
from radish.examplescenario import ExampleScenario
from radish.step import Step
from radish.exceptions import RadishError


class ScenarioOutline(Scenario):
    """
        Represents a Scenario
    """

    class Example(object):
        """
            Represents the ScenarioOutline examples
        """

        def __init__(self, data, path, line):
            self.data = data
            self.path = path
            self.line = line

    def __init__(self, id, keyword, example_keyword, sentence, path, line, parent):
        super(ScenarioOutline, self).__init__(id, keyword, sentence, path, line, parent)
        self.example_keyword = example_keyword
        self.scenarios = []
        self.examples_header = []
        self.examples = []

    def build_scenarios(self):
        """
            Builds the scenarios with the parsed Examples

            Note: This must be done before mering the steps from the feature file with the step definitions
        """
        for row_id, example in enumerate(self.examples):
            examples = dict(zip(self.examples_header, example.data))
            scenario_id = self.id + row_id
            scenario = ExampleScenario(scenario_id, self.keyword, "{} - row {}".format(self.sentence, row_id), self.path, self.line, self, example)
            for step_id, outlined_step in enumerate(self.steps):
                sentence = self._replace_examples_in_sentence(outlined_step.sentence, examples)
                step = Step(step_id + 1, sentence, outlined_step.path, example.line, scenario, False)
                scenario.steps.append(step)
            self.scenarios.append(scenario)

    @classmethod
    def _replace_examples_in_sentence(cls, sentence, examples):
        """
            Replaces the given examples in the given sentece

            :param string sentence: the step sentence in which to replace the examples
            :param dict examples: the examples

            :returns: the new step sentence
            :rtype: string
        """
        for key, value in examples.items():
            sentence = sentence.replace("<{}>".format(key), value)
        return sentence

    def get_column_width(self, column_index):
        """
            Gets the column width from the given column

            :param int column_index: the column index to get the width from
        """
        try:
            return max(max([len(x.data[column_index]) for x in self.examples]), len(self.examples_header[column_index]))
        except IndexError:
            raise RadishError("Invalid colum_index to get column width for ScenarioOutline '{}'".format(self.sentence))