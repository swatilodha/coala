import os
import platform
import unittest

from coalib.bearlib.abstractions.Linter import Linter
from coalib.misc.ContextManagers import prepare_file
from coalib.misc.Shell import escape_path_argument
from coalib.results.RESULT_SEVERITY import RESULT_SEVERITY
from coalib.results.SourceRange import SourceRange
from coalib.settings.Section import Section


class LintTest(unittest.TestCase):

    def setUp(self):
        section = Section("some_name")
        self.uut = Lint(section, None)

    def test_invalid_output(self):
        out = list(self.uut.process_output(
            ["1.0|0: Info message\n",
             "2.2|1: Normal message\n",
             "3.4|2: Major message\n"],
            "a/file.py",
            ['original_file_lines_placeholder']))
        self.assertEqual(len(out), 3)
        self.assertEqual(out[0].origin, "Lint")

        self.assertEqual(out[0].affected_code[0],
                         SourceRange.from_values("a/file.py", 1, 0))
        self.assertEqual(out[0].severity, RESULT_SEVERITY.INFO)
        self.assertEqual(out[0].message, "Info message")

        self.assertEqual(out[1].affected_code[0],
                         SourceRange.from_values("a/file.py", 2, 2))
        self.assertEqual(out[1].severity, RESULT_SEVERITY.NORMAL)
        self.assertEqual(out[1].message, "Normal message")

        self.assertEqual(out[2].affected_code[0],
                         SourceRange.from_values("a/file.py", 3, 4))
        self.assertEqual(out[2].severity, RESULT_SEVERITY.MAJOR)
        self.assertEqual(out[2].message, "Major message")

    def test_custom_regex(self):
        self.uut.output_regex = (r'(?P<origin>\w+)\|'
                                 r'(?P<line>\d+)\.(?P<column>\d+)\|'
                                 r'(?P<end_line>\d+)\.(?P<end_column>\d+)\|'
                                 r'(?P<severity>\w+): (?P<message>.*)')
        self.uut.severity_map = {"I": RESULT_SEVERITY.INFO}
        out = list(self.uut.process_output(
            ["info_msg|1.0|2.3|I: Info message\n"],
            'a/file.py',
            ['original_file_lines_placeholder']))
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].affected_code[0].start.line, 1)
        self.assertEqual(out[0].affected_code[0].start.column, 0)
        self.assertEqual(out[0].affected_code[0].end.line, 2)
        self.assertEqual(out[0].affected_code[0].end.column, 3)
        self.assertEqual(out[0].severity, RESULT_SEVERITY.INFO)
        self.assertEqual(out[0].origin, 'Lint (info_msg)')

    def test_valid_output(self):
        out = list(self.uut.process_output(
            ["Random line that shouldn't be captured\n",
             "*************\n"],
            'a/file.py',
            ['original_file_lines_placeholder']))
        self.assertEqual(len(out), 0)

    def test_stdin_input(self):
        with prepare_file(["abcd", "efgh"], None) as (lines, filename):
            # Use more which is a command that can take stdin and show it.
            # This is available in windows and unix.
            if platform.system() == "Windows":
                # Windows maps `more.com` to `more` only in shell, but `Lint`
                # doesn't use it.
                self.uut.executable = "more.com"
            else:
                self.uut.executable = "more"
            self.uut.use_stdin = True
            self.uut.use_stderr = False
            self.uut.process_output = lambda output, filename, file: output

            out = self.uut.lint(file=lines)
            # Some implementations of `more` add an extra newline at the end.
            self.assertTrue(("abcd\n", "efgh\n") == out or
                            ("abcd\n", "efgh\n", "\n") == out)

    def test_stderr_output(self):
        self.uut.executable = "echo"
        self.uut.arguments = "hello"
        self.uut.use_stdin = False
        self.uut.use_stderr = True
        self.uut.process_output = lambda output, filename, file: output
        out = self.uut.lint("unused_filename")
        self.assertEqual((), out)  # stderr is used

        self.uut.use_stderr = False
        out = self.uut.lint("unused_filename")
        self.assertEqual(('hello\n',), out)  # stdout is used

        def assert_warn(line):
            assert line == "hello"
        old_warn = self.uut.warn
        self.uut.warn = assert_warn
        self.uut._print_errors(["hello", "\n"])
        self.uut.warn = old_warn

    def test_gives_corrected(self):
        self.uut.gives_corrected = True
        out = tuple(self.uut.process_output(["a", "b"], "filename", ["a", "b"]))
        self.assertEqual((), out)
        out = tuple(self.uut.process_output(["a", "b"], "filename", ["a"]))
        self.assertEqual(len(out), 1)

    def test_missing_binary(self):
        old_binary = Lint.executable
        invalid_binary = "invalid_binary_which_doesnt_exist"
        Lint.executable = invalid_binary

        self.assertEqual(Lint.check_prerequisites(),
                         "'{}' is not installed.".format(invalid_binary))

        # "echo" is existent on nearly all platforms.
        Lint.executable = "echo"
        self.assertTrue(Lint.check_prerequisites())

        del Lint.executable
        self.assertTrue(Lint.check_prerequisites())

        Lint.executable = old_binary

    def test_config_file_generator(self):
        self.uut.executable = "echo"
        self.uut.arguments = "-c {config_file}"

        self.assertEqual(
            self.uut._create_command(config_file="configfile").strip(),
            "echo -c " + escape_path_argument("configfile"))

    def test_config_file_generator(self):
        self.uut.executable = "echo"
        self.uut.config_file = lambda: ["config line1"]
        config_filename = self.uut.generate_config_file()
        self.assertTrue(os.path.isfile(config_filename))
        os.remove(config_filename)

        # To complete coverage of closing the config file and check if any
        # errors are thrown there.
        self.uut.lint("filename")


class LinterTest(unittest.TestCase):

    class EmptyTestLinter:
        pass

    class ConfigurationTestLinter:
        @staticmethod
        def generate_config(filename, file, val):
            return "config_value = " + str(val)

    @staticmethod
    def get_full_testfile_name(name):
        return os.path.join(os.path.dirname(os.path.realpath(__file__)),
                            "linter_test_files",
                            name)

    def test_decorator_creation(self):
        with self.assertRaises(ValueError):
            Linter("some-executable", invalid_arg=88)

        with self.assertRaises(ValueError):
            Linter("some-executable", diff_severity=RESULT_SEVERITY.MAJOR)

        with self.assertRaises(ValueError):
            Linter("some-executable", diff_message="Custom message")

        with self.assertRaises(ValueError):
            Linter("some-executable",
                   provides_correction=True,
                   output_regex=".*")

        with self.assertRaises(ValueError):
            Linter("some-executable",
                   provides_correction=True,
                   severity_map={})

    def test_get_executable(self):
        uut = Linter("some-executable")(self.EmptyTestLinter)
        self.assertEqual(uut.get_executable(), "some-executable")

    def test_check_prerequisites(self):
        test_program_path = self.get_full_testfile_name("stdout_stderr.py")
        uut = Linter(test_program_path)(self.EmptyTestLinter)
        self.assertTrue(uut.check_prerequisites())

        uut = Linter("invalid_nonexisting_programv412")(self.EmptyTestLinter)
        self.assertEqual(uut.check_prerequisites(),
                         "'invalid_nonexisting_programv412' is not installed.")

    def test_execute_command(self):
        test_program_path = self.get_full_testfile_name("stdout_stderr.py")
        uut = Linter(test_program_path)(self.EmptyTestLinter)

        # The test program puts out the stdin content (only the first line) to
        # stdout and the arguments passed to stderr.
        stdout, stderr = uut._execute_command(["some_argument"],
                                              "display content")

        self.assertEqual(stdout, "display content")
        self.assertEqual(stderr, "['some_argument'']")

    def test_process_output_corrected(self):
        # TODO Ahhh I need to instantiate the bear...
        uut_cls = Linter("", provides_correction=True)(self.EmptyTestLinter)
        uut = uut_cls()

    def test_process_output_issues(self):
        pass

    def test_grab_output(self):
        uut = Linter("", use_stderr=False)(self.EmptyTestLinter)
        self.assertEqual(uut._grab_output("std", "err"), "std")

        uut = Linter("", use_stderr=True)(self.EmptyTestLinter)
        self.assertEqual(uut._grab_output("std", "err"), "err")

    def test_pass_file_as_stdin_if_needed(self):
        uut = Linter("", stdin=False)(self.EmptyTestLinter)
        self.assertIsNone(uut._pass_file_as_stdin_if_needed(["contents"]))

        uut = Linter("", stdin=True)(self.EmptyTestLinter)
        self.assertEqual(uut._pass_file_as_stdin_if_needed(["contents"]),
                         ["contents"])

    def test_generate_config(self):
        uut = Linter("")(self.EmptyTestLinter)
        with uut._create_config("filename", []) as config_file:
            self.assertIsNone(config_file)

        uut = Linter("")(self.ConfigurationTestLinter)
        with uut._create_config("filename", [], val=88) as config_file:
            self.assertTrue(os.path.isfile(config_file))
            with open(config_file, mode="r") as fl:
                self.assertEqual(fl.read(), "config_value = 88")
        self.assertFalse(os.path.isfile(config_file))

    def test_run(self):
        pass
