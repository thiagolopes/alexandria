#! /bin/python3
import argparse
from http import HTTPStatus
from functools import cache
import html
import os
import json
import re
import subprocess
import sys
from datetime import datetime
from functools import cached_property
from http.server import HTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse
from dataclasses import dataclass, field, asdict
from pathlib import Path
from enum import Flag, auto


class SnapshotStaticNotFound(Exception):
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

        self.original_url = url
        self.scheme = url_p.scheme
        self.netloc = url_p.netloc
        self.path = url_p.path
        self.params = url_p.params
        self.query = url_p.query
        self.fragment = url_p.fragment

    def __hash__(self):
        return hash(self.original_url)

    def __str__(self):
        return self.original_url


class ProcessChoices(Flag):
    SERVE = auto()
    SNAPSHOT_WEBSITE = auto()
    GENERATE_MARKDOWN = auto()
    GENERATE_THUMBNAIL = auto()


@dataclass
class AlxConfig:
    path: Path
    generate_readme: bool = True
    readme_name: str = "README.md"

    debug: bool = False
    server_port: int = 8000

    skip_download: bool = False  # debug only

    db_name: str = "database.json"
    db_statics_name: str = "mirrors"

    def __post_init__(self):
        self.path = Path(self.path)

    @property
    def skip(self):
        return self.debug and self.skip_download

    @property
    def db(self) -> Path:
        return (self.path / self.db_name).absolute()

    @property
    def db_statics(self) -> Path:
        return (self.path / self.db_statics_name).absolute()

    @property
    def readme(self) -> Path:
        return (self.path / self.readme_name).absolute()

    @property
    def statics_server(self) -> Path:
        return Path("./static")


class SnapshotStaticsFiles:
    def __init__(self, path):
        self.base_path = Path(path)

    def __iter__(self):
        for directory in self.base_path.iterdir():
            if directory.is_dir():
                yield directory

    def __len__(self):
        return len(list(self.__iter__()))

    def list_all_snapshot_domains(self) -> list[str]:
        for directory in self.__iter__():
            yield directory.name

    def resolve_snapshot_index(self, url: URL) -> Path:
        path = self.base_path / Path(f"{url.netloc}/{url.path}")

        possibles_files = [
            path,
            path.parent,
            Path(str(path) + ".html"),
            Path(str(path.parent) + ".html"),
            path / "index.html",
            path.parent / "index.html",
            path / ("index.html@" + url.query + ".html"),
            path.parent / ("index.html@" + url.query + ".html"),
        ]
        # if str(url) == "https://chromium.googlesource.com/chromiumos/docs/+/master/constants/syscalls.md": breakpoint()
        for f in possibles_files:
            if f.is_file():
                return f

        err = "\n".join(str(p) for p in possibles_files)
        raise SnapshotStaticNotFound(
            (
                "unreachable - cound not determinate the html file!\n"
                f"url: {url}\n"
                "all the patterns checked:\n"
                f"{err}"
                "\nplease patch me\n"
            )
        )

    def size_domain_by_url(self, url: URL) -> int:
        path = self.base_path / url.netloc
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


# ss = SnapshotStaticsFiles("./alx/mirrors")
# print(len(ss))
# print(list(ss.list_all_snapshot_domains()))
# print(ss._directory_size(ss.base_path))
# url = "https://bruop.github.io/frustum_culling/"
# url = URL("https://learnopengl.com/Guest-Articles/2021/Scene/Frustum-Culling")
# print(ss.size_domain_by_url(url))
# print(ss.size_domain_by_url(URL("https://naoexit.com")))


class HTMLFile:
    # this only parses basic tags, do not use as AST analizer

    re_find_title = re.compile(
        r"<title.*?>(.+?)</title>", flags=re.IGNORECASE | re.DOTALL
    )

    def __init__(self, file_path: Path):
        self.file_path = file_path

    def title(self):
        bytes_to_read = int(self.file_path.stat().st_size * 0.3)

        with open(self.file_path, "r") as f:
            html_cont = f.read(bytes_to_read)

        if match := self.re_find_title.search(html_cont):
            return html.unescape(match.groups()[0])
        return ""


@dataclass(eq=False)
class SnapshotPage:
    url: URL
    title: str = field(repr=False)
    size: int = field(repr=False)
    index_snapshot: Path = field(repr=False)
    created_at: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        self.url = URL(str(self.url))
        if not isinstance(self.created_at, datetime):
            self.created_at = datetime.fromisoformat(self.created_at)

    def __hash__(self):
        return hash(self.url)

    def __eq__(self, other):
        return other.url == self.url

    @classmethod
    def from_statics(
        cls, statics: SnapshotStaticsFiles, url: str, created_at: datetime | None = None
    ):
        url_k = URL(url)
        index_html = statics.resolve_snapshot_index(url_k)
        title = HTMLFile(index_html).title()
        size = statics.size_domain_by_url(url_k)

        if created_at:
            return cls(
                url_k,
                title,
                size,
                index_html.relative_to(statics.base_path),
                created_at,
            )
        return cls(url_k, title, size, index_html)

    def dump(self):
        return {"url": self.url, "created_at": self.created_at}


# sp = SnapshotPage.from_static(ss.resolve_snapshot_index(url), url, ss.size_by_domain(url))
# sp2 = SnapshotPage.from_static(ss.resolve_snapshot_index(url), url, ss.size_by_domain(url))
# print(sp == sp2)
# print(sp)
# print(sp.dump())


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


# db = NeoDatabase("./alx/database.json")
# db.load()
# # db.save()
# print(len(db["websites"]))


class Exporter:
    def __init__(self, snapshots: list[SnapshotPage]):
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
            url = url_str[:max_trunc] + "(...)"
        return url_str

    def humanize_datetime(self, dt):
        datetime_fmt = "%d. %B %Y %I:%M%p"
        return dt.strftime(datetime_fmt)

    def generate(self):
        pass


class MarkDownExporter(Exporter):
    def website_md_line(self, snapshot: SnapshotPage):
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
    def website_detail_list(self, snapshot: SnapshotPage):
        title = self.clean_title(snapshot.title)
        url = self.trunc_url(snapshot.url)
        index_path = snapshot.index_snapshot
        size = self.humanize_size(snapshot.size)
        created_at = self.humanize_datetime(snapshot.created_at)

        return f"""
        <tr>
            <td class="td_title">{title}</td>
            <td><a href="{index_path}">{url}</a></td>
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
    def __init__(self, config: AlxConfig):
        self.config = config
        self.db = NeoDatabase(config.db)
        self.statics = SnapshotStaticsFiles(config.db_statics)
        self.db.initial_migration()

    def genereate_html_snapshots_list(self):
        self.db.load()
        snaps = []
        for snapshot in self.db["websites"]:
            sp = SnapshotPage.from_statics(
                self.statics, snapshot["url"], snapshot["created_at"]
            )
            snaps.append(sp)
        return HTMLExporter(snaps[::-1]).generate()


class AlexandriaStaticServer(SimpleHTTPRequestHandler):
    template_name = "./static/index.html"
    stylesheet = "./static/index.css"
    debug = False
    alx = None

    @cached_property
    def html_template(self):
        with open(self.template_name, "r") as f:
            return f.read()

    def log_message(self, fmt, *args):
        if self.debug:
            return super().log_message(fmt, *args)

    def response(self, status_code, content, content_type="text/html"):
        self.send_response(status_code)
        self.send_header("Content-type", content_type)
        self.end_headers()
        self.wfile.write(bytes(content, "utf-8"))

    def index(self):
        content = self.html_template.format(
            css=self.stylesheet, table=self.alx.genereate_html_snapshots_list()
        )
        return self.response(HTTPStatus.OK, content)

    def do_GET(self):
        if self.path == "/":
            return self.index()
        return super().do_GET()


def run_server(config: AlxConfig, server=HTTPServer, handler=AlexandriaStaticServer):
    # shell_link_mask = "\u001b]8;;{}\u001b\\{}\u001b]8;;\u001b\\"
    # title_print(f"Start server at {pref.server_port}")
    # title_print(shell_link_mask.format(f"http://localhost:{pref.server_port}", f"http://localhost:{pref.server_port}"))
    server_addr = ("", config.server_port)
    handler.debug = config.debug
    handler.alx = Alexandria(config)
    httpd = server(server_addr, handler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        httpd.server_close()
        # title_print(f"Alexandria server:{pref.server_port} ended!")
        sys.exit()


def download_website_static(url: URL, mirrors_path):
    domain = url.hostname

    cmd = ["wget"]
    cmd.extend(["-P", str(mirrors_path)])
    cmd.extend(["--mirror", "-p", "--recursive", "-l", "1"])
    cmd.extend(["--page-requisites", "--adjust-extension", "--span-hosts"])
    cmd.extend(["-U", "'Mozilla'", "-E", "-k"])
    cmd.extend(["-e", "robots=off", "--random-wait", "--no-cookies"])
    cmd.extend(["--convert-links", "--restrict-file-names=windows"])
    cmd.extend(["--domains", str(domain)])
    cmd.extend(["--no-parent", str(url)])

    # debug_print("command: {}".format(" ".join(cmd)))
    subprocess.run(cmd, check=False)
    # title_print(f"Finished {url}!!!")


def generate_md_database(content, database_file):
    with open(database_file, "wb") as f:
        f.write(bytes(content, "utf-8"))
    # debug_print(f"Database {database_file} generated...")


if __name__ == "__main__":
    print("Alexandria - CLI website preservation")
    parser = argparse.ArgumentParser(
        prog="Alexandria",
        description="A tool to manage your personal website backup libary",
        epilog="Keep and hold",
    )
    parser.add_argument("url", help="One or more internet links (URL)", nargs="*")
    parser.add_argument(
        "-p",
        "--port",
        help="The port to run server, 8000 is default",
        default=AlxConfig.server_port,
        type=int,
    )
    parser.add_argument(
        "-v",
        "--verbose",
        help="Enable verbose",
        default=AlxConfig.debug,
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
        "--readme",
        help="Generate the database README.",
        default=True,
        action=argparse.BooleanOptionalAction,
        type=bool,
    )
    args = parser.parse_args()

    url_to_download = args.url
    config = AlxConfig(
        path="./alx",
        server_port=args.port,
        debug=args.verbose,
        generate_readme=args.readme,
        skip_download=args.skip,
    )

    # server it - bye!
    if not url_to_download:
        run_server(config)
        sys.exit()

    if config.skip:
        print("BYPASSING THE PROCESS OF DOWNLOAD - you are on your own")
    else:
        for url in url_to_download:
            download_website_static(url, config.db_statics)
            webpage = WebPage(url, config.db_statics)
            # database.add(webpage)

    # database.save()
    # generate_md_database(database.to_md(), config.readme)
