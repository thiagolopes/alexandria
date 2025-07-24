from hashlib import md5
import argparse
import html
import json
import re
import subprocess
import sys
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Flag, auto
from functools import cache, cached_property, partial
from http import HTTPStatus
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse


class ProgramDependencyNotFound(Exception):
    pass


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

    def unique(self):
        return md5(str(self.original_url).encode("utf-8")).hexdigest()


class CLIActionChoices(Flag):
    SERVE = auto()
    ADD = auto()
    EXPORT = auto()
    UPDATE = auto()


@dataclass(kw_only=True)
class Config:
    path: Path = Path("alx")
    migrate: bool = False
    generate_readme: bool = False
    readme_file_name: str = "README.md"

    debug: bool = False
    server_port: int = 8000

    urls: list[Path] = field(default_factory=list)
    download_deep: int = 1

    _db_name: str = "database.json"
    _db_statics_name: str = "mirrors"

    def __post_init__(self):
        self.path = Path(self.path)
        for i, url in enumerate(self.urls):
            self.urls[i] = URL(url)

    @property
    def db(self) -> Path:
        return (self.path / self._db_name).absolute()

    @property
    def db_statics(self) -> Path:
        return (self.path / self._db_statics_name).absolute()

    @property
    def screenshots_path(self) -> Path:
        return (self.path / "screenshots").absolute()

    @property
    def readme(self) -> Path:
        return (self.path / self.readme_file_name).absolute()

    @classmethod
    def from_args_parse(cls, parser):
        args = parser.parse_args()
        return cls(
            path=args.directory,
            urls=args.urls,
            generate_readme=args.readme,
            readme_file_name=args.readme_file_name,
            server_port=args.port,
            debug=args.verbose,
            download_deep=args.download_deep,
            migrate=args.migrate,
        )

    def get_choice(self) -> CLIActionChoices:
        action = CLIActionChoices(0)

        if self.migrate:
            action |= CLIActionChoices.UPDATE
        if self.generate_readme is True:
            action |= CLIActionChoices.EXPORT

        if self.urls:
            action |= CLIActionChoices.ADD
        else:
            action |= CLIActionChoices.SERVE
        return action


class StaticsFiles:
    def __init__(self, path, relative=None):
        self.path = Path(path)
        self.relative = Path(relative).absolute()
        self.initial_migration()

    def __iter__(self):
        # fix to iter over files too...
        for directory in self.path.iterdir():
            if directory.is_dir():
                yield directory

    def __len__(self):
        return len(list(self.__iter__()))

    def initial_migration(self):
        self.path.mkdir(exist_ok=True, parents=True)

    def relative_resolve(self):
        if not self.relative:
            return None
        return self.path.relative_to(self.relative)

    @cache
    def directory_size(self, path: Path) -> int:
        total = 0
        for e in path.iterdir():
            if e.is_dir():
                total += self.directory_size(e)
            if e.is_file():
                total += e.stat().st_size
        return total


@cache
class HTMLFile:
    # this only parses basic tags, do not use as AST analizer
    # using HTMLParser from html.parser shows slower, maybe later.

    re_find_title = re.compile(
        r"<title.*?>(.+?)</title>", flags=re.IGNORECASE | re.DOTALL
    )

    def __init__(self, file_path: Path):
        self.file_path = file_path

    def title(self):
        read_bytes = int(self.file_path.stat().st_size * 0.5)  # 50% arbitrary number

        with open(self.file_path, "rb") as f:
            html_cont = f.read(read_bytes).decode("utf-8")

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

    def screenshot_file(self):
        return self.url.unique() + ".png"


@dataclass(kw_only=True)
class StaticSnapshot(Snapshot):
    title: str = field(repr=False)
    size: int = field(repr=False)
    index_file: Path = field(repr=False)
    screenshot: Path = field(repr=False)

    @classmethod
    def from_statics(
        cls,
        ss_statics: StaticsFiles,
        statics: StaticsFiles,
        url: str,
        created_at: datetime,
    ):
        url_k = URL(str(url))
        size = cls.size_domain_by_url(statics, url_k)
        index_html = cls.resolve_snapshot_index(statics, url_k)
        screenshot = f"{url_k.unique()}.png"
        title = HTMLFile(index_html).title()

        return cls(
            url=url_k,
            created_at=created_at,
            title=title,
            size=size,
            index_file=index_html.relative_to(statics.relative),
            screenshot=ss_statics.relative_resolve() / screenshot,
        )

    @staticmethod
    def resolve_snapshot_index(statics: StaticsFiles, url: URL) -> Path:
        path = statics.path / Path(f"{url.netloc}/{url.path}")

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

    @staticmethod
    def size_domain_by_url(statics: StaticsFiles, url: URL) -> int:
        path = statics.path / url.netloc
        if not path.exists():
            return 0
        return statics.directory_size(path)


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
        with open(self.database_file, "r") as f:
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
    def __init__(self, snapshots: list[StaticSnapshot]):
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
    def website_md_line(self, snapshot: StaticSnapshot):
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
    def website_detail_list(self, snapshot: StaticSnapshot):
        title = self.clean_title(snapshot.title)
        snap_url = self.trunc_url(snapshot.url)
        url = snapshot.index_file
        screenshot = snapshot.index_file
        size = self.humanize_size(snapshot.size)
        created_at = self.humanize_datetime(snapshot.created_at)

        return f"""
        <tr>
            <td class="td_title">{title}</td>
            <td><a href="{url}">{snap_url}</a></td>
            <td><span><a href="{snapshot.screenshot}">&#x1F4F7;</a></span></td>
            <td>{size}</td>
            <td>{created_at}</td>
        </tr>"""

    def generate(self):
        table = """<table>
            <tr>
            <th>Title</th>
            <th>URL</th>
            <th>SS</th>
            <th>Size</th>
            <th>Created at</th>
            </tr>\n"""
        return table + " ".join(self.website_detail_list(web) for web in self.snapshots)


class Alexandria:
    def __init__(self, config: Config):
        self.config = config
        self.db = NeoDatabase(config.db)
        self.stats_snapshots = StaticsFiles(config.db_statics, config.path)
        self.stats_screenshots = StaticsFiles(config.screenshots_path, config.path)
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

    def get_snapshot_statics(self, snap: Snapshot) -> StaticSnapshot:
        return StaticSnapshot.from_statics(
            self.stats_screenshots, self.stats_snapshots, snap.url, snap.created_at
        )

    def insert_snapshot(self, snap: Snapshot):
        self.validate_db()
        self.db.insert_one(self.snapshot_column_name, snap.json())

    def get_snapshots(self) -> list[Snapshot]:
        self.validate_db()
        return (Snapshot(**snapshot) for snapshot in self.db[self.snapshot_column_name])

    def get_snapshots_static(self) -> list[StaticSnapshot]:
        self.validate_db()
        return (
            StaticSnapshot.from_statics(
                self.stats_screenshots,
                self.stats_snapshots,
                snapshot["url"],
                snapshot["created_at"],
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


class Process:
    required: bool = False
    quiet: bool = False
    cmd: str

    @cached_property
    def available(self):
        return shutil.which(self.cmd)

    def run(self, cmd) -> int:
        if not self.available:
            if self.required:
                raise ProgramDependencyNotFound(
                    f"{self.__class__.__name__} is a required dependency, please install it using your package manager"
                )
            return 1

        stderr = None
        stdout = None
        if self.quiet:
            stderr = subprocess.DEVNULL
            stdout = subprocess.DEVNULL
        return subprocess.run(
            cmd, check=False, stderr=stderr, stdout=stdout
        ).check_returncode


class Chromium(Process):
    quiet = True
    cmd = "chromium"

    def __init__(self, path: Path):
        self.path = path

    def screenshot(self, url: URL, dest):
        cmd = [self.cmd]
        cmd.extend(
            [
                "--run-all-compositor-stages-before-draw",
                "--disable-gpu",
                "--headless=new",
                "--virtual-time-budget=30000",
                "--hide-scrollbars",
                "--window-size=1920,4000",
            ]
        )
        cmd.append(f"--screenshot={self.path / dest}")
        cmd.append(str(url))

        return self.run(cmd)


class WGet(Process):
    required = True
    cmd = "wget"

    def __init__(self, path: Path, deep=1):
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
        cmd.extend(
            [
                "--header",
                "User-Agent: Mozilla/5.0 (compatible; Heritrix/3.0 +http://archive.org)",
            ]
        )
        cmd.extend(["--header", "Accept: text/html,application/xhtml+xml"])
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

        return self.run(cmd)


def run_server(config: Config, server=HTTPServer, handler=AlexandriaStaticServer):
    # shell_link_mask = "\u001b]8;;{}\u001b\\{}\u001b]8;;\u001b\\"
    # title_print(f"Start server at {pref.server_port}")
    # title_print(shell_link_mask.format(f"http://localhost:{pref.server_port}", f"http://localhost:{pref.server_port}"))
    alx = Alexandria(config)
    server_addr = ("", config.server_port)
    handler.debug = config.debug
    handler.alx = alx

    httpd = server(server_addr, partial(handler, directory=config.path))
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()


def add_snapshots(config: Config):
    wget = WGet(config.db_statics, deep=config.download_deep)
    screenshoter = Chromium(config.screenshots_path)
    urls = config.urls
    alx = Alexandria(config)

    # check if already downloaded
    for url in urls:
        if alx.get_snapshot(url):
            print(f"{url} is already in the database snapshots - skiping the download")
            continue

        snapshot = Snapshot(url=url)

        wget.fetch_site(url)
        screenshoter.screenshot(url, snapshot.screenshot_file())

        # validate if exists on statisc - success download
        if alx.get_snapshot_statics(snapshot):
            alx.insert_snapshot(snapshot)

    alx.save()


def export_readme(config):
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
        default=Config.server_port,
        type=int,
    )
    parser.add_argument(
        "--download-deep",
        help="How deep in links should download",
        default=Config.download_deep,
        type=int,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Enable verbose",
        default=Config.debug,
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
        "--migrate",
        default=Config.migrate,
        help="Re-download all assets",
        action=argparse.BooleanOptionalAction,
        type=bool,
    )
    parser.add_argument(
        "--readme",
        help="Generate the database README.",
        default=Config.generate_readme,
        type=bool,
    )
    parser.add_argument(
        "--readme-file-name",
        help="Name to use in README generation.",
        default=Config.readme_file_name,
        type=str,
    )
    parser.add_argument(
        "--directory",
        help="Path to store database and statics to serve.",
        default=Config.path,
        type=Path,
    )
    config = Config.from_args_parse(parser)

    action = config.get_choice()
    if CLIActionChoices.ADD in action:
        add_snapshots(config)

        if CLIActionChoices.UPDATE in action:
            pass
        if CLIActionChoices.EXPORT in action:
            export_readme(config)

    if CLIActionChoices.SERVE in action:
        run_server(config)

    print("Αντίο/bye/مع السلامة!")


if __name__ == "__main__":
    main()
