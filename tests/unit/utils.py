import os

import shutil
import tempfile
import unittest

# disable for stestr otherwise output is much too verbose
from hotsos.core.log import log, logging, setup_logging
from hotsos.core.config import HotSOSConfig, setup_config

# Must be set prior to other imports
TESTS_DIR = os.environ["TESTS_DIR"]
DEFAULT_FAKE_ROOT = 'fake_data_root/openstack'
setup_config(DATA_ROOT=os.path.join(TESTS_DIR, DEFAULT_FAKE_ROOT))


def expand_log_template(template, hours=None, mins=None, secs=None,
                        lstrip=False):
    """
    Expand a given template log sequence using a sequence of hours/mins/secs.

    @param lstrip: optionally lstrip() the template before using it.
    """
    out = ""
    if lstrip:
        _template = template.lstrip()
    else:
        _template = template

    for hour in range(hours or 1):
        if hour < 10:
            hour = "0{}".format(hour)
        for min in range(mins or 1):
            if min < 10:
                min = "0{}".format(min)
            for sec in range(secs or 1):
                if sec < 10:
                    sec = "0{}".format(sec)
                out += _template.format(hour=hour, min=min, sec=sec)

    return out


def is_def_filter(def_filename):
    """
    Filter hotsos.core.ycheck.YDefsLoader._is_def to only match a file with the
    given name. This permits a unit test to only run the ydef checks that are
    under test.

    Note that in order for directory globals to run def_filename must be a
    relative path that includes the parent directory name e.g. foo/bar.yaml
    where bar contains the checks and there is also a file called foo/foo.yaml
    that contains directory globals.
    """
    def inner(_inst, abs_path):
        # filename may optionally have a parent dir which allows us to permit
        # directory globals to be run.
        parent_dir = os.path.dirname(def_filename)
        """ Ensure we only load/run the yaml def with the given name. """
        if parent_dir:
            # allow directory global to run
            base_dir = os.path.basename(os.path.dirname(abs_path))
            if base_dir != parent_dir:
                return False

            if os.path.basename(abs_path) == "{}.yaml".format(parent_dir):
                return True

        if abs_path.endswith(def_filename):
            return True

        return False

    return inner


def create_data_root(files_to_create, copy_from_original=None):
    """
    Decorator helper to create any number of files with provided content within
    a temporary DATA_ROOT.

    @param files_to_create: a dictionary of <filename>: <contents> pairs.
    @param copy_from_original: a list of files to copy from the original
                                     data root into this test one.
    """

    def create_files_inner1(f):
        def create_files_inner2(*args, **kwargs):
            with tempfile.TemporaryDirectory() as dtmp:
                for _file in copy_from_original or []:
                    src = os.path.join(HotSOSConfig.DATA_ROOT, _file)
                    dst = os.path.join(dtmp, _file)
                    if not os.path.exists(os.path.dirname(dst)):
                        os.makedirs(os.path.dirname(dst))

                    shutil.copy(src, dst)

                for path, content in files_to_create.items():
                    path = os.path.join(dtmp, path)
                    if not os.path.exists(os.path.dirname(path)):
                        os.makedirs(os.path.dirname(path))

                    log.debug("creating test file %s", path)
                    with open(path, 'w') as fd:
                        fd.write(content)

                setup_config(DATA_ROOT=dtmp)
                return f(*args, **kwargs)

        return create_files_inner2

    return create_files_inner1


class BaseTestCase(unittest.TestCase):

    def part_output_to_actual(self, output):
        actual = {}
        for key, entry in output.items():
            actual[key] = entry.data

        return actual

    def setUp(self):
        self.maxDiff = None
        # ensure locale consistency wherever tests are run
        os.environ["LANG"] = 'C.UTF-8'
        self.global_tmp_dir = tempfile.mkdtemp()
        self.plugin_tmp_dir = tempfile.mkdtemp(dir=self.global_tmp_dir)
        # Always reset env globals
        # If a test relies on loading info from defs yaml this needs to be set
        # to actual plugin name.
        setup_config(DATA_ROOT=os.path.join(TESTS_DIR, DEFAULT_FAKE_ROOT),
                     PLUGIN_NAME="testplugin",
                     PLUGIN_YAML_DEFS=os.path.join(TESTS_DIR, "defs"),
                     PART_NAME="01part",
                     GLOBAL_TMP_DIR=self.global_tmp_dir,
                     PLUGIN_TMP_DIR=self.plugin_tmp_dir,
                     USE_ALL_LOGS=True)
        setup_logging(debug_mode=True)
        log.setLevel(logging.INFO)

    def tearDown(self):
        if os.path.isdir(self.plugin_tmp_dir):
            shutil.rmtree(self.plugin_tmp_dir)
