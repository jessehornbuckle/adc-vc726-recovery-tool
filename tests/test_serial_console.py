from vc726_recovery.constants import BOOT_INTERRUPT
from vc726_recovery.serial_console import SerialConsole


class FakeSerial:
    is_open = True

    def __init__(self, on_write=None):
        self.writes = []
        self.on_write = on_write

    def write(self, data):
        self.writes.append(data)
        if self.on_write:
            self.on_write()

    def flush(self):
        pass


def test_interrupt_repeats_across_requested_window():
    console = SerialConsole(lambda _text: None, lambda _error: None)
    fake = FakeSerial()
    console._serial = fake

    console.interrupt_boot(attempts=3, interval=0)

    assert fake.writes == [BOOT_INTERRUPT, BOOT_INTERRUPT, BOOT_INTERRUPT]


def test_interrupt_stops_after_prompt_is_observed_across_chunks():
    console = SerialConsole(lambda _text: None, lambda _error: None)

    def send_split_prompt():
        console._observe_boot_prompt("HK")
        console._observe_boot_prompt("VS #")

    fake = FakeSerial(on_write=send_split_prompt)
    console._serial = fake

    console.interrupt_boot()

    assert fake.writes == [BOOT_INTERRUPT]
