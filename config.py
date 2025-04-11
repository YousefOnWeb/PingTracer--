import argparse


class Config(argparse.ArgumentParser):
    """
    An ArgumentParser subclass to define configuration options for the ping script.
    """

    def __init__(self):
        super().__init__(
            description="A script that pings a domain with configurable settings.",
            formatter_class=argparse.ArgumentDefaultsHelpFormatter,
        )

        self.add_argument(
            "domain",
            nargs="?",  # Makes the positional argument optional
            default="google.com",  # Default value if not provided
            metavar="DOMAIN",  # Often good practice for positional args help
            help="The domain or IP address to ping.",
        )

        # Ping Rate
        self.add_argument(
            "--ping-rate",
            "-r",
            type=float,
            default=1.0,
            metavar="RATE",  # Add metavar for clarity in help
            help="Number of pings per second.",
        )

        # Ping Timeout
        self.add_argument(
            "--ping-timeout",
            "-t",
            type=float,
            default=1.0,
            metavar="SECONDS",
            help="Timeout for each ping in seconds.",
        )

        # Ping Size
        self.add_argument(
            "--ping-size",
            "-s",
            type=int,
            default=1,  # Note: Very small default size for ICMP. Often defaults are larger (e.g., 32, 56, 64)
            metavar="BYTES",
            help="Payload size for each ping in bytes.",
        )

        # Bad Threshold
        self.add_argument(
            "--bad-threshold",
            "-b",
            type=int,
            default=100,
            metavar="MS",
            help="Latency threshold (ms) to consider a ping 'bad' (e.g., yellow).",
        )

        # So Bad Threshold
        self.add_argument(
            "--so-bad-threshold",
            "-B",
            type=int,
            default=200,
            metavar="MS",
            help="Latency threshold (ms) to consider a ping 'so bad' (e.g., red).",
        )

