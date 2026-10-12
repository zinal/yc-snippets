from yc_snippets.yc_walk import parse_help


SAMPLE = """\
List virtual machine instances

Usage:
  yc compute instance list [Flags...] [Global Flags...]

Flags:
      --limit int   The maximum number of items to list. Default is 1000 items

Use "yc help [command]" for more information about a command and global flags.
"""

GROUPS = """\
Manage Yandex Compute Cloud resources

Usage:
  yc compute <group|command>

Groups:
  disk                   Manage disks
  instance               Manage virtual machine instances

Commands:
  connect-to-serial-port Connect to serial port

Use "yc help [command]" for more information about a command and global flags.
"""


def test_parse_list_help_extracts_description_and_flags():
    _groups, _commands, flags, description = parse_help(SAMPLE)
    assert description == "List virtual machine instances"
    assert flags == ["--limit"]


def test_parse_group_help_extracts_groups_and_commands():
    groups, commands, _flags, _description = parse_help(GROUPS)
    assert [name for name, _desc in groups] == ["disk", "instance"]
    assert [name for name, _desc in commands] == ["connect-to-serial-port"]
