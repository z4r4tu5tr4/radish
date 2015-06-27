# -*- coding: utf-8 -*-

import os
import io
import re
import json

from radish.exceptions import RadishError, FeatureFileSyntaxError, LanguageNotSupportedError
from radish.feature import Feature
from radish.scenario import Scenario
from radish.scenariooutline import ScenarioOutline
from radish.scenarioloop import ScenarioLoop
from radish.step import Step


class Keywords(object):
    """
        Represent config object for gherkin keywords.
    """
    def __init__(self, feature, scenario, scenario_outline, examples, scenario_loop, iterations):
        self.feature = feature
        self.scenario = scenario
        self.scenario_outline = scenario_outline
        self.examples = examples
        self.scenario_loop = scenario_loop
        self.iterations = iterations


class FeatureParser(object):
    """
        Class to parse a feature file.
        A feature file contains just one feature.
    """

    LANGUAGE_LOCATION = os.path.join(os.path.dirname(__file__), "languages")
    DEFAULT_LANGUAGE = "en"

    class State(object):
        """
            Represents the parser state
        """
        INIT = "init"
        FEATURE = "feature"
        SCENARIO = "scenario"
        SCENARIO_OUTLINE = "scenario_outline"
        STEP = "step"
        EXAMPLES = "examples"
        EXAMPLES_ROW = "examples_row"
        SCENARIO_LOOP = "scenario_loop"
        STEP_TEXT = "step_text"

    def __init__(self, core, featurefile, featureid, language="en"):
        if not os.path.exists(featurefile):
            raise OSError("Feature file at '{}' does not exist".format(featurefile))

        self._core = core
        self._featureid = featureid
        self._featurefile = featurefile
        self.keywords = {}
        self._keywords_delimiter = ":"

        self._current_state = FeatureParser.State.FEATURE
        self._current_line = 0
        self._current_tags = []
        self._current_preconditions = []
        self._current_variables = []
        self._in_step_text = False
        self.feature = None

        self._load_language(language)

    def _load_language(self, language=None):
        """
            Loads all keywords of the given language

            :param string language: the lanugage to use for the feature files.
                                    if None is given `radish` tries to detect the language.

            :returns: if the language could be loaded or not
            :rtype: bool

            :raises LanguageNotSupportedError: if the given language is not supported by radish
        """
        if not language:  # try to detect language
            raise NotImplementedError("Auto detect language is not implemented yet")

        language_path = os.path.join(self.LANGUAGE_LOCATION, language + ".json")
        if not os.path.exists(language_path):
            raise LanguageNotSupportedError(language)

        with io.open(language_path, "r", encoding="utf-8") as f:
            language_pkg = json.load(f)

        self.keywords = Keywords(**language_pkg["keywords"])

    def parse(self):
        """
            Parses the feature file of this `FeatureParser` instance

            :returns: if the parsing was successful or not
            :rtype: bool
        """
        with io.open(self._featurefile) as f:
            for line in f.readlines():
                self._current_line += 1
                line = line.strip()
                if not line:  # line is empty
                    continue

                if line.startswith("#"):
                    # try to detect feature file language
                    language = self._detect_language(line)
                    if language:
                        self._load_language(language)

                    continue

                if self.feature and self._detect_feature(line):
                    raise FeatureFileSyntaxError("radish supports only one Feature per feature file")

                if not self._parse_context(line):
                    raise FeatureFileSyntaxError("Syntax error in feature file {} on line {}".format(self._featurefile, self._current_line))
        if not self.feature:
            raise FeatureFileSyntaxError("No Feature found in file {}".format(self._featurefile))

        if self.feature.scenarios:
            self.feature.scenarios[-1].after_parse()

    def _parse_context(self, line):
        """
            Parses arbitrary context from a line

            :param string line: the line to parse from
        """
        parse_context_func = getattr(self, "_parse_" + self._current_state)
        if not parse_context_func:
            raise RadishError("FeatureParser state {} is not support".format(self._current_state))

        return parse_context_func(line)

    def _parse_feature(self, line):
        """
            Parses a Feature Sentence

            The `INIT` state is used as initiale state.

            :param string line: the line to parse from
        """
        detected_feature = self._detect_feature(line)
        if not detected_feature:
            tag = self._detect_tag(line)
            if tag:
                self._current_tags.append(Feature.Tag(tag[0], tag[1]))
                if tag[0] == "variable":
                    name, value = self._parse_variable(tag[1])
                    self._current_variables.append((name, value))
                return True

            return False

        self.feature = Feature(self._featureid, self.keywords.feature, detected_feature, self._featurefile, self._current_line, self._current_tags)
        self.feature.context.variables = self._current_variables
        self._current_state = FeatureParser.State.SCENARIO
        self._current_tags = []
        self._current_variables = []
        return True

    def _parse_scenario(self, line):
        """
            Parses a Feature context

            :param string line: the line to parse from
        """
        detected_scenario = self._detect_scenario(line)
        scenario_type = Scenario
        keywords = (self.keywords.scenario,)
        if not detected_scenario:
            detected_scenario = self._detect_scenario_outline(line)
            scenario_type = ScenarioOutline
            keywords = (self.keywords.scenario_outline, self.keywords.examples)

            if not detected_scenario:
                detected_scenario = self._detect_scenario_loop(line)
                if not detected_scenario:
                    tag = self._detect_tag(line)
                    if tag:
                        self._current_tags.append(Scenario.Tag(tag[0], tag[1]))
                        if tag[0] == "precondition":
                            scenario = self._parse_precondition(tag[1])
                            self._current_preconditions.append(scenario)
                        elif tag[0] == "variable":
                            name, value = self._parse_variable(tag[1])
                            self._current_variables.append((name, value))
                        return True

                    self.feature.description.append(line)
                    return True

                detected_scenario, iterations = detected_scenario  # pylint: disable=unpacking-non-sequence
                scenario_type = ScenarioLoop
                keywords = (self.keywords.scenario_loop, self.keywords.iterations)

        if detected_scenario in self.feature:
            raise FeatureFileSyntaxError("Scenario with name '{}' defined twice in feature '{}'".format(detected_scenario, self.feature.sentence))

        scenario_id = len(self.feature.scenarios) + 1
        if self.feature.scenarios:
            previous_scenario = self.feature.scenarios[-1]
            if isinstance(previous_scenario, ScenarioOutline):
                scenario_id += len(previous_scenario.examples)
            elif isinstance(previous_scenario, ScenarioLoop):
                scenario_id += previous_scenario.iterations

        self.feature.scenarios.append(scenario_type(scenario_id, *keywords, sentence=detected_scenario, path=self._featurefile, line=self._current_line, parent=self.feature, tags=self._current_tags, preconditions=self._current_preconditions))
        self.feature.scenarios[-1].context.variables = self._current_variables
        self._current_tags = []
        self._current_preconditions = []
        self._current_variables = []

        if scenario_type == ScenarioLoop:
            self.feature.scenarios[-1].iterations = iterations
        self._current_state = FeatureParser.State.STEP
        return True

    def _parse_examples(self, line):
        """
            Parses the Examples header line

            :param string line: the line to parse from
        """
        if not isinstance(self.feature.scenarios[-1], ScenarioOutline):
            raise FeatureFileSyntaxError("Scenario does not support Examples. Use 'Scenario Outline'")

        self.feature.scenarios[-1].examples_header = [x.strip() for x in line.split("|")[1:-1]]
        self._current_state = FeatureParser.State.EXAMPLES_ROW
        return True

    def _parse_examples_row(self, line):
        """
            Parses an Examples row

            :param string line: the line to parse from
        """
        # detect next keyword
        if self._detect_scenario(line) or self._detect_scenario_outline(line) or self._detect_scenario_loop(line):
            self.feature.scenarios[-1].after_parse()
            return self._parse_scenario(line)

        example = ScenarioOutline.Example([x.strip() for x in line.split("|")[1:-1]], self._featurefile, self._current_line)
        self.feature.scenarios[-1].examples.append(example)
        return True

    def _parse_step(self, line):
        """
            Parses a single step

            :param string line: the line to parse from
        """
        # detect next keyword
        if self._detect_scenario(line) or self._detect_scenario_outline(line) or self._detect_scenario_loop(line) or self._detect_tag(line):
            self.feature.scenarios[-1].after_parse()
            return self._parse_scenario(line)

        if self._detect_step_text(line):
            self._current_state = self.State.STEP_TEXT
            return self._parse_step_text(line)

        if self._detect_table(line):
            self._parse_table(line)
            return True

        if self._detect_examples(line):
            self._current_state = FeatureParser.State.EXAMPLES
            return True

        step_id = len(self.feature.scenarios[-1].all_steps) + 1
        not_runable = isinstance(self.feature.scenarios[-1], (ScenarioOutline, ScenarioLoop))
        step = Step(step_id, line, self._featurefile, self._current_line, self.feature.scenarios[-1], not not_runable)
        self.feature.scenarios[-1].steps.append(step)
        return True

    def _parse_table(self, line):
        """
            Parses a step table row

            :param string line: the line to parse from
        """
        if not self.feature.scenarios[-1].steps:
            raise FeatureFileSyntaxError("Found step table without previous step definition on line {}".format(self._current_line))

        self.feature.scenarios[-1].steps[-1].table.append([x.strip() for x in line.split("|")[1:-1]])
        return True

    def _parse_step_text(self, line):
        """
            Parses additional step text

            :param str line: the line to parse
        """
        if line.startswith('"""') and not self._in_step_text:
            self._in_step_text = True
            line = line[3:]

        if line.endswith('"""') and self._in_step_text:
            self._current_state = self.State.STEP
            self._in_step_text = False
            line = line[:-3]

        if line:
            self.feature.scenarios[-1].steps[-1].raw_text.append(line.strip())
        return True

    def _parse_precondition(self, arguments):
        """
            Parses scenario preconditions

            The arguments must be in format:
                File.feature: Some scenario

            :param str arguments: the raw arguments
        """
        match = re.search(r"(.*?\.feature): (.*)", arguments)
        if not match:
            raise FeatureFileSyntaxError("Scenario @precondition tag must have argument in format: 'test.feature: Some scenario'")

        feature_file_name, scenario_sentence = match.groups()
        feature_file = os.path.join(os.path.dirname(self._featurefile), feature_file_name)

        try:
            feature = self._core.parse_feature(feature_file)
        except RuntimeError as e:
            if str(e) == "maximum recursion depth exceeded":  # precondition cycling
                raise FeatureFileSyntaxError("You feature '{}' has cycling preconditions with '{}: {}' starting at line {}".format(self._featurefile, feature_file_name, scenario_sentence, self._current_line))
            raise

        if scenario_sentence not in feature:
            raise FeatureFileSyntaxError("Cannot import precondition scenario '{}' from feature '{}': No such scenario".format(scenario_sentence, feature_file))

        return feature[scenario_sentence]

    def _parse_variable(self, arguments):
        """
            Parses tag arguments as a variable containing name and value

            The arguments must be in format:
                VariableName: SomeValue
                VariableName: 5

            :param str arguments: the raw arguments to parse
        """
        name, value = arguments.split(":", 1)
        return name.strip(), value.strip()

    def _detect_feature(self, line):
        """
            Detects a feature on the given line

            :param string line: the line to detect a feature

            :returns: if a feature was found on the given line
            :rtype: bool
        """
        if line.startswith(self.keywords.feature + self._keywords_delimiter):
            return line[len(self.keywords.feature) + len(self._keywords_delimiter):].strip()

        return None

    def _detect_scenario(self, line):
        """
            Detects a scenario on the given line

            :param string line: the line to detect a scenario

            :returns: if a scenario was found on the given line
            :rtype: bool
        """
        if line.startswith(self.keywords.scenario + self._keywords_delimiter):
            return line[len(self.keywords.scenario) + len(self._keywords_delimiter):].strip()

        return None

    def _detect_scenario_outline(self, line):
        """
            Detects a scenario outline on the given line

            :param string line: the line to detect a scenario outline

            :returns: if a scenario outline was found on the given line
            :rtype: bool
        """
        if line.startswith(self.keywords.scenario_outline + self._keywords_delimiter):
            return line[len(self.keywords.scenario_outline) + len(self._keywords_delimiter):].strip()

        return None

    def _detect_examples(self, line):
        """
            Detects an Examples block on the given line

            :param string line: the line to detect the Examples

            :returns: if an Examples block was found on the given line
            :rtype: bool
        """
        if line.startswith(self.keywords.examples + self._keywords_delimiter):
            return True

        return None

    def _detect_scenario_loop(self, line):
        """
            Detects a scenario loop on the given line

            :param string line: the line to detect a scenario loop

            :returns: if a scenario loop was found on the given line
            :rtype: string
        """
        match = re.search(r"^{} (\d+):(.*)".format(self.keywords.scenario_loop), line)
        if match:
            return match.group(2).strip(), int(match.group(1))

        return None

    def _detect_table(self, line):
        """
            Detects a step table row on the given line

            :param string line: the line to detect the table row

            :returns: if an step table row was found or not
            :rtype: bool
        """
        return line.startswith("|")

    def _detect_step_text(self, line):
        """
            Detects the beginning of an additional step text block

            :param str line: the line to detect the step text block

            :returns: if a step text block was found or not
            :rtype: bool
        """
        return line.startswith('"""')

    def _detect_language(self, line):
        """
            Detects a language on the given line

            :param string line: the line to detect the language

            :returns: the language or None
            :rtype: str or None
        """
        match = re.search("^# language: (.*)", line)
        if match:
            return match.group(1)

        return None

    def _detect_tag(self, line):
        """
            Detects a tag on the given line

            :param string line: the line to detect the tag

            :returns: the tag or None
            :rtype: str or None
        """
        match = re.search(r"^@([^\s(]+)(?:\((.*?)\))?", line)
        if match:
            return match.group(1), match.group(2)

        return None
