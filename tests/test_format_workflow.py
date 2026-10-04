from vc726_recovery.format_workflow import (
    FormatHelpOutcome,
    FormatRunOutcome,
    LinuxRebootHelpOutcome,
    classify_format_help,
    classify_format_run,
    classify_linux_reboot_help,
)


def test_exact_proven_format_help_is_verified():
    output = (
        "Help for 'format': format app_pri app_sec cfg_pri cfg_sec partitions\r\n"
        "HKVS #"
    )
    assert classify_format_help(output) == FormatHelpOutcome.VERIFIED


def test_format_help_waits_for_prompt_before_proceeding():
    output = "Help for 'format': format app_pri app_sec cfg_pri cfg_sec partitions\r\n"
    assert classify_format_help(output) == FormatHelpOutcome.PENDING


def test_format_help_rejects_an_extra_partition():
    output = (
        "Help for 'format': format krn_pri app_pri app_sec cfg_pri cfg_sec partitions\r\n"
        "HKVS #"
    )
    assert classify_format_help(output) == FormatHelpOutcome.MISMATCH


def test_format_help_without_expected_description_fails_at_prompt():
    assert classify_format_help("Use help for help\r\nHKVS #") == FormatHelpOutcome.ERROR


def test_format_run_detects_observed_linux_shell_completion():
    assert classify_format_run("Erasing app partitions...") == FormatRunOutcome.PENDING
    output = (
        "Formatting ................................ done!\r\n\r\n"
        "BusyBox v1.2.1 Protect Shell (psh)\r\n# "
    )
    assert classify_format_run(output) == FormatRunOutcome.REBOOT_REQUIRED


def test_format_run_accepts_uboot_after_reboot():
    assert (
        classify_format_run("Erasing app partitions...done\r\nHKVS #")
        == FormatRunOutcome.BOOTLOADER_READY
    )


def test_format_run_stops_on_error_even_if_prompt_returns():
    output = "format error: erase failed\r\nHKVS #"
    assert classify_format_run(output) == FormatRunOutcome.ERROR


def test_linux_help_requires_completed_prompt_before_accepting_reboot():
    assert classify_linux_reboot_help("help\r\nreboot\r\n") == LinuxRebootHelpOutcome.PENDING
    assert (
        classify_linux_reboot_help("help\r\ndmesg reboot reset\r\n# ")
        == LinuxRebootHelpOutcome.SUPPORTED
    )


def test_linux_help_does_not_mistake_echo_for_reboot_support():
    output = "help\r\ndmesg prtHardInfo\r\n# "
    assert classify_linux_reboot_help(output) == LinuxRebootHelpOutcome.UNSUPPORTED
