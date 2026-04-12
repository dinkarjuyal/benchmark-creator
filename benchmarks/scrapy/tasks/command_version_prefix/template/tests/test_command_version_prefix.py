from argparse import Namespace

import scrapy

from scrapy.commands.version import Command


def test_version_command_non_verbose_output_starts_with_scrapy_prefix(capsys):
    command = Command()
    command.run([], Namespace(verbose=False))

    assert capsys.readouterr().out.strip() == f"Scrapy {scrapy.__version__}"
