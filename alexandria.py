#! /bin/python3
import argparse
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime
from enum import Flag, auto
from functools import cache, cached_property, partial
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse


class StaticNotFound(Exception):
    pass


class InvalidURL(Exception):
    pass


@dataclass(init=False)
class URL:
    scheme: str
    netloc: str
    path: str
    params: str
    query: str
    fragment: str

    original_url: str

    def __init__(self, url):
        url_p = urlparse(url)

        if not url_p.scheme and not url_p.netloc:
            raise InvalidURL(f"{url} is not a valid URL")

        if url_p.scheme not in ["", "https", "http"]:
            raise InvalidURL(f"{url} is not HTTP or HTTPS")

        self.original_url = url
        self.scheme = url_p.scheme
        self.netloc = url_p.netloc
        self.path = url_p.path
        self.params = url_p.params
        self.query = url_p.query
        self.fragment = url_p.fragment

    def __eq__(self, other):
        return self.original_url == other.original_url

    def __hash__(self):
        return hash(self.original_url)

    def __str__(self):
        return self.original_url


class CLIActionChoices(Flag):
    SERVE = auto()
    SNAPSHOT_SITE = auto()
    GENERATE_README = auto()
    GENERATE_THUMBNAILS = auto()


@dataclass(kw_only=True)
class Config:
    path: Path

    _generate_readme: bool
    _readme_name: str

    quiet: bool
    debug: bool
    server_port: int

    urls: list[Path] = field(default_factory=list)
    download_deep: int
    _skip_download: bool = False  # debug only

    _db_name: str = "database.json"
    _db_statics_name: str = "mirrors"

    def __post_init__(self):
        self.path = Path(self.path)
        for i, url in enumerate(self.urls):
            self.urls[i] = URL(url)

    @property
    def skip(self):
        return self.debug and self._skip_download

    @property
    def db(self) -> Path:
        return (self.path / self._db_name).absolute()

    @property
    def db_statics(self) -> Path:
        return (self.path / self._db_statics_name).absolute()

    @property
    def readme(self) -> Path:
        return (self.path / self._readme_name).absolute()

    @classmethod
    def from_args_parse(cls, parser):
        args = parser.parse_args()
        return cls(
            path=args.directory,
            urls=args.urls,
            _generate_readme=args.readme,
            _readme_name=args.readme_file_name,
            server_port=args.port,
            quiet=args.quiet,
            debug=args.verbose,
            _skip_download=args.skip,
            download_deep=args.download_deep,
        )

    def get_choice(self) -> CLIActionChoices:
        if self._generate_readme is True:
            return CLIActionChoices.GENERATE_README
        if self.urls:
            return CLIActionChoices.SNAPSHOT_SITE
        return CLIActionChoices.SERVE


class StaticsFiles:
    def __init__(self, path):
        self.path = Path(path)
        self.initial_migration()

    def __iter__(self):
        for directory in self.path.iterdir():
            if directory.is_dir():
                yield directory

    def __len__(self):
        return len(list(self.__iter__()))

    def initial_migration(self):
        self.path.mkdir(exist_ok=True, parents=True)

    def list_all_snapshot_domains(self) -> list[str]:
        for directory in self.__iter__():
            yield directory.name

    def resolve_snapshot_index(self, url: URL) -> Path:
        path = self.path / Path(f"{url.netloc}/{url.path}")

        possibles_files = [
            path,
            path / "index.html",
            str(path) + ".html",
            str(path) + ("index.html@" + url.query + ".html"),
            str(path) + ("@" + url.query + ".html"),
        ]
        for f in possibles_files:
            fp = Path(f)
            if fp.is_file():
                return fp

        err = "\n".join(str(p) for p in possibles_files)
        raise StaticNotFound(
            (
                "unreachable - cound not determinate the html file!\n"
                f"url: {url}\n"
                "all the patterns checked:\n"
                f"{err}"
                "\nplease patch me\n"
            )
        )

    def size_domain_by_url(self, url: URL) -> int:
        path = self.path / url.netloc
        if not path.exists():
            return 0
        return self._directory_size(path)

    @cache
    def _directory_size(self, path: Path) -> int:
        total = 0
        for e in path.iterdir():
            if e.is_dir():
                total += self._directory_size(e)
            if e.is_file():
                total += e.stat().st_size
        return total


class HTMLFile:
    # this only parses basic tags, do not use as AST analizer
    # using HTMLParser from html.parser shows slower, maybe later.

    re_find_title = re.compile(
        r"<title.*?>(.+?)</title>", flags=re.IGNORECASE | re.DOTALL
    )

    def __init__(self, file_path: Path):
        self.file_path = file_path

    def title(self):
        bytes_to_read = int(self.file_path.stat().st_size * 0.5)  # 50% arbitrary number

        with open(self.file_path, "r") as f:
            html_cont = f.read(bytes_to_read)

        if re_match := self.re_find_title.search(html_cont):
            return html.unescape(re_match.groups()[0])
        return self.file_path.name


@dataclass(kw_only=True)
class Snapshot:
    url: URL
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        self.url = URL(str(self.url))
        if not isinstance(self.created_at, datetime):
            self.created_at = datetime.fromisoformat(self.created_at)

    def __hash__(self):
        return hash(self.url)

    def __eq__(self, other):
        assert isinstance(other, type(self)), type(other)
        return other.url == self.url

    def json(self):
        return {"url": str(self.url), "created_at": self.created_at.isoformat()}


# convert to Snapshot contains a list with StaticSnapshots.
@dataclass(kw_only=True)
class SnapshotStatic(Snapshot):
    title: str = field(repr=False)
    size: int = field(repr=False)
    index_file: Path = field(repr=False)

    @classmethod
    def from_statics(cls, statics: StaticsFiles, url: str, created_at: datetime):
        url_k = URL(str(url))
        index_html = statics.resolve_snapshot_index(url_k)
        title = HTMLFile(index_html).title()
        size = statics.size_domain_by_url(url_k)

        return cls(
            url=url_k,
            created_at=created_at,
            title=title,
            size=size,
            index_file=index_html.relative_to(statics.path),
        )


class NeoDatabase:
    def __init__(self, database_file: Path):
        self.database_file = database_file
        self.data = {}  # memory database

    def __contains__(self, value):
        return bool(value in self.data)

    def __getitem__(self, key):
        return self.data.get(key)

    def __setitem__(self, key, value):
        self.data[key] = value

    def initial_migration(self):
        if self.database_file.exists():
            return

        self.database_file.touch()
        self.save()
        self.load()

    def save(self):
        # print("[DATABASE] Saving mirrors-list on disk...")
        with open(self.database_file, "w") as db:
            json.dump(self.data, db, indent=4)
        # print("[DATABASE] Saved.")

    def load(self):
        with open(self.database_file, "rb") as f:
            self.data = json.load(f)
        # print("[DATABASE] Load")

    def insert_one(self, collection, data):
        self.data.setdefault(collection, list()).append(data)

    def find_one(self, collection, query):
        if collection not in self.data:
            return

        for row in self.data[collection]:
            if isinstance(query, dict) and isinstance(row, dict):
                if all(row.get(k) == v for k, v in query.items()):
                    return row
            elif row == query:
                return row


class Exporter:
    def __init__(self, snapshots: list[SnapshotStatic]):
        self.snapshots = snapshots

    def clean_title(self, title):
        return title.replace("|", "-").replace("\n", "")

    def humanize_size(self, num):
        if num == 0:
            return "0 B"

        KiB = 1024
        units = ("KiB", "MiB", "GiB")
        for u in units:
            num /= KiB
            if abs(num) < KiB:
                break
        return f"{num:3.1f} {u}"

    def trunc_url(self, url: URL, max_trunc=45):
        url_str = (
            str(url)
            .removeprefix("https://")
            .removeprefix("http://")
            .removeprefix("www.")
        )
        if len(url_str) > max_trunc:
            url_str = url_str[:max_trunc] + "(...)"
        return url_str

    def humanize_datetime(self, dt):
        datetime_fmt = "%d. %B %Y %I:%M%p"
        return dt.strftime(datetime_fmt)

    def generate(self):
        pass


class MDExporter(Exporter):
    def website_md_line(self, snapshot: SnapshotStatic):
        title = self.clean_title(snapshot.title)
        url = snapshot.url
        created_at = self.humanize_datetime(snapshot.created_at)
        return f"| [{title}]({url}) | {created_at} |"

    def generate(self):
        today = self.humanize_datetime(datetime.now())
        md_table = "\n".join(self.website_md_line(web) for web in self.snapshots)
        return (
            f"# Alexandria - generated at {today}\n"
            "| Site | Created at |\n"
            "| ---- | ---------- |\n"
            f"{md_table}\n"
        )


class HTMLExporter(Exporter):
    def website_detail_list(self, snapshot: SnapshotStatic):
        title = self.clean_title(snapshot.title)
        snap_url = self.trunc_url(snapshot.url)
        url = snapshot.index_file
        size = self.humanize_size(snapshot.size)
        created_at = self.humanize_datetime(snapshot.created_at)

        return f"""
        <tr>
            <td class="td_title">{title}</td>
            <td><a href="{url}">{snap_url}</a></td>
            <td>{size}</td>
            <td>{created_at}</td>
        </tr>"""

    def generate(self):
        table = """<table>
            <tr>
            <th>Title</th>
            <th>URL</th>
            <th>Size</th>
            <th>Created at</th>
            </tr>\n"""
        return table + " ".join(self.website_detail_list(web) for web in self.snapshots)


class Alexandria:
    def __init__(self, config: Config):
        self.config = config
        self.db = NeoDatabase(config.db)
        self.statics = StaticsFiles(config.db_statics)
        self.db.initial_migration()
        self.snapshot_column_name = "websites"
        self.initial_migration()

    def save(self):
        self.db.save()

    def initial_migration(self):
        try:
            self.validate_db()
        except AssertionError:
            self.db[self.snapshot_column_name] = []
            self.db.save()

    def get_snapshot(self, url: URL):
        all_snaps = set(self.get_snapshots())
        snap = Snapshot(url=url)
        return snap if snap in all_snaps else None
        # if self.db.find_one(self.snapshot_column_name, {"url": str(url)}):
        #     return True
        # return False

    def validate_db(self):
        self.db.load()
        db_snaps = self.db[self.snapshot_column_name]
        assert db_snaps is not None, "missing 'websites' in database"

    def get_snapshot_statics(self, snap: Snapshot) -> SnapshotStatic:
        return SnapshotStatic.from_statics(self.statics, snap.url, snap.created_at)

    def insert_snapshot(self, snap: Snapshot):
        self.validate_db()
        self.db.insert_one(self.snapshot_column_name, snap.json())

    def get_snapshots(self) -> list[Snapshot]:
        self.validate_db()
        return (Snapshot(**snapshot) for snapshot in self.db[self.snapshot_column_name])

    def get_snapshots_static(self) -> list[SnapshotStatic]:
        self.validate_db()
        return (
            SnapshotStatic.from_statics(
                self.statics, snapshot["url"], snapshot["created_at"]
            )
            for snapshot in self.db[self.snapshot_column_name]
        )

    def genereate_html_snapshots_list(self) -> str:
        self.db.load()
        snaps = self.get_snapshots_static()
        return HTMLExporter(list(snaps)[::-1]).generate()

    def generate_readme_snapshots_list(self) -> str:
        self.db.load()
        snaps = self.get_snapshots_static()
        return MDExporter(list(snaps)[::-1]).generate()


class AlexandriaStaticServer(SimpleHTTPRequestHandler):
    template_name = Path("./static/index.html")
    stylesheet = Path("./static/index.css")
    debug = False
    alx: Alexandria | None = None

    @cached_property
    def html_template(self):
        with open(self.template_name, "r") as f:
            return f.read()

    @cached_property
    def css(self):
        with open(self.stylesheet, "r") as f:
            return f.read()

    def log_message(self, format, *args):
        if self.debug:
            return super().log_message(format, *args)

    def response(self, status_code, content, content_type="text/html"):
        self.send_response(status_code)
        self.send_header("Content-type", content_type)
        self.end_headers()
        self.wfile.write(bytes(content, "utf-8"))

    def index(self):
        assert self.alx is not None, "Missing Alexandria instance"
        table_content = self.alx.genereate_html_snapshots_list()
        content = self.html_template.format(css=self.css, table=table_content)
        return self.response(HTTPStatus.OK, content)

    def do_GET(self):
        if self.path == "/":
            return self.index()
        return super().do_GET()


class WGet:
    def __init__(self, path: Path, deep=1):
        self.cmd = "wget"
        self.deep = deep
        self.path = path

    def add_browser_headers(self, cmd, gzip=False):
        cmd.extend(
            [
                "--header",
                "Accept: text/html,application/xhtml+xml,"
                "application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            ]
        )
        cmd.extend(["--header", "Accept-Language: pt-BR,pt;q=0.9,en;q=0.8"])
        cmd.extend(["--header", "DNT: 1"])
        cmd.extend(["--header", "Connection: keep-alive"])
        cmd.extend(["--header", "Upgrade-Insecure-Requests: 1"])
        cmd.extend(["--header", "Sec-Fetch-Dest: document"])
        cmd.extend(["--header", "Sec-Fetch-Mode: navigate"])
        cmd.extend(["--header", "Sec-Fetch-Site: none"])
        cmd.extend(["--header", "Sec-Fetch-User: ?1"])
        cmd.extend(["--header", "Cache-Control: max-age=0"])
        if gzip:
            cmd.extend(["--header", "Accept-Encoding: gzip, deflate, br"])

    def fetch_site(self, url: URL):
        cmd = [self.cmd]

        self.add_browser_headers(cmd)
        cmd.extend(["-P", str(self.path)])
        cmd.extend(["--mirror", "-p", "--recursive"])
        cmd.extend(["-l", str(self.deep)])
        cmd.extend(["--page-requisites", "--adjust-extension", "--span-hosts"])
        cmd.extend(["-U", "'Mozilla'", "-E", "-k"])
        cmd.extend(["-e", "robots=off", "--random-wait", "--no-cookies"])
        cmd.extend(["--convert-links", "--restrict-file-names=windows"])
        cmd.extend(["--domains", url.netloc])
        cmd.extend(["--no-parent", str(url)])

        return subprocess.run(cmd, check=False).check_returncode


def run_server(config: Config, server=HTTPServer, handler=AlexandriaStaticServer):
    # shell_link_mask = "\u001b]8;;{}\u001b\\{}\u001b]8;;\u001b\\"
    # title_print(f"Start server at {pref.server_port}")
    # title_print(shell_link_mask.format(f"http://localhost:{pref.server_port}", f"http://localhost:{pref.server_port}"))
    alx = Alexandria(config)
    server_addr = ("", config.server_port)
    handler.debug = config.quiet
    handler.alx = alx

    httpd = server(server_addr, partial(handler, directory=alx.statics.path))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()


def snapshot_static_site(config: Config):
    wget = WGet(config.db_statics, deep=config.download_deep)
    urls = config.urls
    alx = Alexandria(config)

    # check if already_exists
    # check if was success to add on db
    for url in urls:
        if alx.get_snapshot(url):
            print(f"{url} is already in the database snapshots - skiping the download")
            continue

        wget.fetch_site(url)
        snapshot = Snapshot(url=url)
        if alx.get_snapshot_statics(
            snapshot
        ):  # validate if exists on statisc - success download
            alx.insert_snapshot(snapshot)

    alx.save()
    print(f"snapshot action finalized")


def generate_readme(config):
    alx = Alexandria(config)
    content = alx.generate_readme_snapshots_list()
    with open(config.readme, "w") as f:
        f.write(content)


def main():
    print("Αλεξάνδρεια/Alexandria/الإسكندرية - Internet preservation")
    parser = argparse.ArgumentParser(
        prog="Alexandria",
        description="A tool to manage your personal website backup libary",
        epilog="Keep and hold",
    )
    parser.add_argument(
        "urls", help="One or a list of URLs to snapshot websites", nargs="*"
    )
    parser.add_argument(
        "-p",
        "--port",
        help="The port to run server, 8000 is default",
        default=8000,
        type=int,
    )
    parser.add_argument(
        "--download-deep",
        help="How deep in links should download",
        default=1,
        type=int,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Enable verbose",
        default=False,
        type=bool,
    )
    parser.add_argument(
        "--skip",
        help="Skip download process, only add entry.",
        default=False,
        action=argparse.BooleanOptionalAction,
        type=bool,
    )
    parser.add_argument(
        "--quiet",
        help="Silencie the webserver logs.",
        default=True,
        action=argparse.BooleanOptionalAction,
        type=bool,
    )
    parser.add_argument(
        "--readme",
        help="Generate the database README.",
        default=False,
        type=bool,
    )
    parser.add_argument(
        "--readme-file-name",
        help="Name to use in README generation.",
        default="README.md",
        type=str,
    )
    parser.add_argument(
        "--directory",
        help="Path to store database and statics to serve.",
        default="alx",
        type=Path,
    )
    config = Config.from_args_parse(parser)

    match config.get_choice():
        case CLIActionChoices.SNAPSHOT_SITE:
            snapshot_static_site(config)
            generate_readme(config)
        case CLIActionChoices.GENERATE_README:
            generate_readme(config)
        case CLIActionChoices.SERVE:
            run_server(config)

    print("Αντίο/bye/مع السلامة!")


if __name__ == "__main__":
    main()
