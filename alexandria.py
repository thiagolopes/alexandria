#! /bin/python3
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

# TODO proper logging
log = print

class ExternalDependencyNotFound(Exception):
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
            raise InvalidURL(f"{url} is not valid URL")

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
        # improve this to clamp the file size with some max_size (100MB+) instead arbitrary 50% file size
        read_bytes = int(self.file_path.stat().st_size * 0.5)  # 50% arbitrary number

        with open(self.file_path, "rb") as f:
            html_cont = f.read(read_bytes).decode(errors="replace")

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


# move to here all the commands and logic
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


class ExternalDependency:
    # TODO raise_on_error: bool = False
    raise_not_found: bool = False

    quiet: bool = False
    cmd: list[str]
    args: list[str] | None = None

    def available_cmd(self) -> str:
        for cmd in self.cmd:
            if shutil.which(cmd):
                return cmd
            # TODO log not found

        raise ExternalDependencyNotFound(
            "{} is required dependency, please install"
            " it using your package manager".format("/".join(self.cmd))
        )

    def run(
        self,
        overwrite_args: list[str] | None = None,
        merge_args: bool = False
    ) -> CompletedProcess | None:
        try:
            cmd = self.available_cmd()
        except ExternalDependencyNotFound as err:
            if self.raise_not_found:
                raise err
            log(f"External program not found - {self.cmd}")
            return None

        stderr = None
        stdout = None
        if self.quiet:
            stderr = subprocess.DEVNULL
            stdout = subprocess.DEVNULL

        args = self.args
        if overwrite_args:
            if merge_args:
                args.extend(overwrite_args)
            else:
                args = overwrite_args

        return subprocess.run([cmd] + args, check=False, stderr=stderr, stdout=stdout)

class ScreenshotPage(ExternalDependency):
    quiet = True
    cmd = ["chromium", "chrome"]
    args = [
            "--run-all-compositor-stages-before-draw",
            "--disable-gpu",
            "--headless=new",
            "--virtual-time-budget=30000",
            "--hide-scrollbars",
            "--window-size=1920,4000",
    ]

    def __init__(self, path: Path):
        self.path = path

    def screenshot(self, url: URL, dest):
        args_screenshot = self.args.copy()
        args_screenshot.append(f"--screenshot={self.path / dest}")
        args_screenshot.append(str(url))
        return self.run(args_screenshot)


class WGet(ExternalDependency):
    required = True
    cmd = "wget"
    args = [
        "--header", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "--header", "User-Agent: Mozilla/5.0 (compatible; Heritrix/3.0 +http://archive.org)",
        "--header", "Accept: text/html,application/xhtml+xml",
        "--header", "Accept-Language: pt-BR,pt;q=0.9,en;q=0.8",
        "--header", "DNT: 1",
        "--header", "Connection: keep-alive",
        "--header", "Upgrade-Insecure-Requests: 1",
        "--header", "Sec-Fetch-Dest: document",
        "--header", "Sec-Fetch-Mode: navigate",
        "--header", "Sec-Fetch-Site: none",
        "--header", "Sec-Fetch-User: ?1",
        "--header", "Cache-Control: max-age=0",
        "--mirror",
        "-p",
        "--recursive",
        "--page-requisites",
        "--adjust-extension",
        "--span-hosts",
        "-U", "'Mozilla'",
        "-E",
        "-k",
        "-e", "robots=off", "--random-wait", "--no-cookies",
        "--convert-links", "--restrict-file-names=windows",
    ]

    def __init__(self, path: Path, deep=1, gzip=False):
        args.extend(["-l", str(deep)])
        args.extend(["-P", str(path)])
        if gzip:
            args.extend(["--header", "Accept-Encoding: gzip, deflate, br"])

    def download(self, url: URL):
        args_download = args.copy()
        args_download.extend(["--no-parent", str(url)])
        args_download.extend(["--domains", url.netloc])
        return self.run(args_download)


class Git(ExternalDependency):
    raise_not_found = False
    quiet = False

    cmd = ["git"]
    args = ["-C",]

    def __init__(self, path: Path, init=True):
        self.path = Path(path)
        self.args.append(str(path))

        if init and not self.is_git_repo():
            self.init()

    def is_git_repo(self):
        return (self.path / Path(".git")).is_dir()

    def get_head(self):
        return self.run(["symbolic-ref", "--short", "HEAD"], True)

    def get_origin(self):
        return self.run(["remote"], True)

    def init(self):
        return self.run(["init"], True)

    def push(self):
        pass

    def commit(self, message):
        return self.run(["commit", "-m", message], True)

    def add(self, _file="."):
        return self.run(["add", _file], True)

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
    syncer = Git(config.path)
    urls = config.urls
    alx = Alexandria(config)

    syncer.migrate()

    # check if already downloaded
    new_snapshots = []
    for url in urls:
        if alx.get_snapshot(url):
            print(f"{url} is already in the database snapshots - skiping the download")
            continue

        snapshot = Snapshot(url=url)

        wget.fetch_site(url)
        screenshoter.screenshot(url, snapshot.screenshot_file())

        # validate if exists on statisc - success download
        snapshot_static = alx.get_snapshot_statics(snapshot)
        if snapshot_static:
            alx.insert_snapshot(snapshot)
            new_snapshots.append(snapshot_static.title)

    if (new_snapshots):
        alx.save()
        syncer.add()
        syncer.commit(f"New snapshot(s) {len(new_snapshots)}: {'\n\t'.join(new_snapshots)}")
    # syncer.push()


def migrate(config):
    alx = Alexandria(config)
    wget = WGet(config.db_statics, deep=config.download_deep)
    screenshoter = Chromium(config.screenshots_path)
    syncer = Git(config.path)
    syncer.migrate()

    print("Migrate started.")
    total = 0
    for snapshot in alx.get_snapshots_static():
        print(f"URL: {snapshot.url}")
        wget.fetch_site(snapshot.url)
        screenshoter.screenshot(snapshot.url, snapshot.screenshot_file())

    syncer.add()
    syncer.commit(
        f"Migration completed, total: {total} at {datetime.now().isoformat()}"
    )
    print(f"Migrate finished, total downloads: {total}")


def export_readme(config):
    alx = Alexandria(config)
    content = alx.generate_readme_snapshots_list()
    with open(config.readme, "w") as f:
        f.write(content)


def main():
    parser = argparse.ArgumentParser(
        prog="Alexandria - Internet preservation",
        description="Download websites",
        epilog="Keep and hold",
    )

    parser.add_argument("urls", help="One or multiple URLs to backup", nargs="*")
    parser.add_argument("--generate-readme", help="Generate and exist", default=True, type=bool)
    parser.add_argument("--generate-html", help="Generate and exist", default=True, type=bool)

    parser.add_argument("-p", "--port", help="Server HTTP port", default=8000, type=int)
    parser.add_argument("-v", "--verbose", help="Enable verbose", default=True, type=bool)
    parser.add_argument("--deep", help="How deep should download", default=1, type=int)
    parser.add_argument("--readme", help="Generate the database README.", default="README.md", type=bool)
    parser.add_argument("--database", help="Path to database file.", default="database.json", type=str)
    parser.add_argument("--statics", help="Path to statics.", default=".alx/", type=Path)


    args_parser = parser.parse_args()
    if args_parser.generate_readme:
        pass
        # generate...
    if args_parser.generate_html:
        pass
        # generate...

    # or server or download
    if args_parser.urls:
        for url in urls:
            pass
            # download
        # catch keyboard exit
    elif args_parser.serve:
        pass
        # serve
        # catch keyboard exit

    # if CLIActionChoices.ADD in action:
    #     add_snapshots(config)
    #     if CLIActionChoices.EXPORT in action:
    #         export_readme(config)

    # if CLIActionChoices.UPDATE in action:
    #     migrate(config)
    # if CLIActionChoices.SERVE in action:
    #     run_server(config)

    print("Αντίο/bye/مع السلامة!")


if __name__ == "__main__":
    main()
