#! /bin/python3
import argparse
import html
import os
import pickle
import json
import re
import subprocess
import sys
from datetime import datetime
from functools import cached_property
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from dataclasses import dataclass, field
from pathlib import Path

DEBUG_PRINTER = False

@dataclass
class Preferences:
    library_path: Path
    generate_readme: bool


    debug: bool = False
    server_port: int = 8000
    skip_download: bool = False # debug only 
    db_file_name: str = "database"
    readme_file_name: str = "README.md"
    mirrors_path_name: str = "mirrors"

    def __post_init__(self):
        self.library_path = Path(self.library_path)

    @property
    def skip(self):
        return self.debug and self.skip_download

    @property
    def readme(self) -> Path:
        return (self.library_path / self.readme_file_name).absolute()

    @property
    def db(self) -> Path:
        return (self.library_path / self.db_file_name).absolute()

    @property
    def db_static(self) -> Path:
        return (self.library_path / self.mirrors_path_name).absolute()

def from_static(name):
    return f"./static/{name}"


def border(msg):
    width = 25
    bordered_msg = "*" * width
    bordered_msg += f"\n{msg}\n"
    bordered_msg += "*" * width
    return bordered_msg


def debug_print(log, add_border=False):
    debug_msg = f"[DEBUG] {log}"
    if DEBUG_PRINTER:
        if add_border:
            debug_msg = border(debug_msg)
        print(debug_msg)
    return debug_msg


def title_print(title):
    border_print = "*" * 8
    title_msg = "\n" + border_print + f" {title} " + border_print
    print(title_msg)
    return title_msg


class HTTPServerAlexandria(SimpleHTTPRequestHandler):
    server_version = "HTTPServerAlexandria"
    template_name = from_static("index.html")
    stylesheet = from_static("index.css")
    pref = None

    @cached_property
    def html_template(self):
        with open(self.template_name, "r") as f:
            return f.read()

    def log_message(self, fmt, *args):
        if DEBUG_PRINTER:
            return super().log_message(fmt, *args)

    def response_index(self, status_code, **context):
        template = self.html_template.format(css=self.stylesheet, **context)

        self.send_response(status_code)
        self.send_header("Content-type", "text/html")
        self.end_headers()
        self.wfile.write(bytes(template, "utf-8"))

    def do_GET(self):
        url = urlparse(self.path)

        if url.path == "/":
            database = Database(self.pref.db, self.pref.db_static, self.pref.readme)
            database.load()
            return self.response_index(200, table=database.to_html())
        return super().do_GET()


class WebPage:
    title_re = re.compile(r"<title.*?>(.+?)</title>", flags=re.IGNORECASE | re.DOTALL)

    def __init__(self, url, path: Path, created_at=None):
        self.url = url
        self.path = path
        self.base_path, self.full_path = self.index_path()
        self.title = self.grep_title_from_index()
        self.size = self.calculate_size_disk(self.base_path)

        if created_at is None:
            debug_print(f"[GENERATED] {self!r}")
            self.created_at = datetime.now()
        else:
            debug_print(f"[RELOADED] {self!r}")
            self.created_at = created_at

    def __hash__(self):
        return hash(self.url)

    def __eq__(self, other):
        return other.url == self.url

    def __repr__(self):
        return f"<Mirror url={self.url}>"

    def __str__(self):
        return self.url

    @classmethod
    def from_webpage(cls, other, path):
        # Re-crate mirror from other mirror - migrate
        return cls(other.url, path, other.created_at)

    def index_path(self):
        url = urlparse(self.url)

        path = self.path / Path(url.netloc) / Path(url.path.removeprefix("/").removesuffix("/"))
        possibles_files = [
            Path(path),
            Path(str(path) + ".html"),
            Path(path) / "index.html",
            Path(path) / ("index.html@" + url.query + ".html"),
        ]
        if (not Path(path).is_dir()):
            possibles_files += [p for p in Path(path).parent.glob("*.html")
                                if url.query in str(p)]

        for f in possibles_files:
            if f.is_file():
                return (self.path / url.netloc), str(f)
        # TODO move to a exception
        assert False, ("unreachable - cound not determinate the html file!\n"
                       "check there is any option available: \n") + "\n".join(str(p) for p in possibles_files)

    def grep_title_from_index(self):
        file_text = ""
        with open(self.full_path, "r") as f:
            for line in f.readlines():
                file_text += line
                f = self.title_re.search(file_text)
                if f:
                    return html.unescape(f.groups()[0])
        # TODO move to a exception
        assert False, (f"unreachable - do not found <title> in the html\n"
                       f"-> {self.url} NEED be a staticpage!")

    def calculate_size_disk(self, path):
        total = 0
        with os.scandir(path) as f:
            for e in f:
                if e.is_dir():
                    total += self.calculate_size_disk(e.path)
                if e.is_file():
                    total += e.stat().st_size
        return total

    def to_out(self):
        return {
            "url":self.url,
            "created_at": self.created_at.isoformat(),
        }


class NeoDatabase():
    def __init__(self, database_file: Path):
        self.database_file = database_file
        self.data = {} # memory database

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

    def save(self):
        print("[DATABASE] Saving mirrors-list on disk...")
        with open(self.database_file, "w") as db:
            json.dump(self.data, db)
        print("[DATABASE] Saved.")

    def load(self):
        with open(self.database_file, "rb") as f:
            self.data = json.load(f)
        print("[DATABASE] Load")

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

# import random
# ndb = NeoDatabase(Path("testsdb.json"))
# ndb.initial_migration()
# ndb.load()
# print(ndb.find_one("random", 34))
# print(ndb["version"])
# ndb.insert_one("random", random.randint(0, 1000))
# ndb.insert_one("website", {"url": "http://bin.com"})
# ndb["version"] = 1
# ndb.save()
# print(ndb.find_one("website", {"url": "http://bin.com"}))
# print(ndb.data)

class Exporter:
    def __init__(self, websites):
        self.websites = websites

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

    def trunc_url(self, url, max_trunc=45):
        url = url.removeprefix("https://").removeprefix("http://").removeprefix("www.")
        if len(url) > max_trunc:
            url = url[:max_trunc] + "(...)"
        return url

    def humanize_datetime(self, dt):
        datetime_fmt = "%d. %B %Y %I:%M%p"
        return dt.strftime(datetime_fmt)


class MarkDownExporter(Exporter):
    def website_md_line(self, website):
        title = clean_title(website.title)
        url = self.url
        created_at = humanize_datetime(self.created_at)
        return f"| [{title}]({url}) | {created_at} |"

    def generate(self):
        today = humanize_datetime(datetime.now())
        md_table = "\n".join(self.website_md_line(web) for web in self.websites)
        return (f"# Alexandria - generated at {today}\n"
                "| Site | Created at |\n"
                "| ---- | ---------- |\n"
                f"{md_table}\n")

class HtmlExporter(Exporter):
    def website_detail_list(self, website):
        title = self.clean_title(website.title)
        url = trunc_url(website.url)
        full_path = Path(website.full_path).relative_to(Path(".").absolute())
        size = humanize_size(website.size)
        created_at = humanize_datetime(website.created_at)

        return f"""
        <tr>
            <td class="td_title">{title}</td>
            <td><a href="{full_path}">{url}</a></td>
            <td>{size}</td>
            <td>{created_at}</td>
        </tr>"""

    def generate(self):
        def to_html(self):
            table = """<table>
            <tr>
            <th>Title</th>
            <th>URL</th>
            <th>Size</th>
            <th>Created at</th>
            </tr>\n"""
            return table + " ".join(self.website_detail_list(web) for web in self.websites)

class Database():
    def __init__(self, database_file:Path, static: Path, export_file: str):
        self.db_file = database_file
        self.static_path = static
        self.export_file = export_file
        self.data = []

    def __iter__(self):
        return self.data.__iter__()

    def load(self):
        self.initial_migration_if_need(self.db_file)
        with open(self.db_file, "rb") as f:
            database = pickle.load(f)

        for row in database:
            if isinstance(row, WebPage):
                # REMOVE, move to migration
                debug_print(f"Database old loaded! - total: {len(self.data)}")
                self.add(WebPage.from_webpage(row, self.static_path))
            else:
                debug_print(f"Database loaded! - total: {len(self.data)}")
                self.add(WebPage(**row, path=self.static_path))
        assert len(database) == len(self.data)

    def initial_migration_if_need(self, path):
        file_disk = Path(path)

        if not file_disk.exists():
            file_disk.parent.mkdir(exist_ok=True, parents=True)
            self.save(self.data)
            debug_print("Initial migration done!")

    def add(self, mr):
        if mr not in self.data:
            self.data.append(mr)
        else:
            title_print(f"Skip add {mr.url}, already in")

    def save(self, data=None):
        if data is None:
            data = self.data

        debug_print("Saving mirrors-list on disk...")
        with open(self.db_file, "wb") as f:
            # keeps its overwriting, redo keeping writing and append if it get wrost
            output_data = [d.to_out() for d in data]
            pickle.dump(output_data, f, pickle.HIGHEST_PROTOCOL)
        debug_print("Saved.")

        with open(self.export_file, "wb") as f_export:
            f_export.write(bytes(self.to_md(), "utf-8"))
        debug_print(f"Database {self.db_file} generated.")


def serve(pref: Preferences):
    shell_link_mask = "\u001b]8;;{}\u001b\\{}\u001b]8;;\u001b\\"

    server = HTTPServerAlexandria
    server.pref = pref
    title_print(f"Start server at {pref.server_port}")
    title_print(shell_link_mask.format(f"http://localhost:{pref.server_port}", f"http://localhost:{pref.server_port}"))

    with HTTPServer(("", pref.server_port), server) as httpd:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            httpd.server_close()
            title_print(f"Alexandria server:{pref.server_port} ended!")
            sys.exit()


def process_download(url, mirrors_path):
    urlp = urlparse(url)
    if not bool(urlp.scheme):
        title_print(f"Not valid url - {url}")
        sys.exit()

    domain = urlp.hostname
    title_print(f"Making a mirror of: {url} at {domain}")

    wget_process = (f"wget"
                    f" -P {mirrors_path}"
                    f" --mirror -p --recursive -l 1 --page-requisites --adjust-extension --span-hosts"
                    f" -U 'Mozilla' -E -k"
                    f" -e robots=off --random-wait --no-cookies"
                    f" --convert-links --restrict-file-names=windows --domains {domain}"
                    f" --no-parent {url}".split(" "))

    debug_print("command: {}".format(" ".join(wget_process)))
    subprocess.run(wget_process, check=False)
    title_print(f"Finished {url}!!!")


def generate_md_database(content, database_file):
    with open(database_file, "wb") as f:
        f.write(bytes(content, "utf-8"))
    debug_print(f"Database {database_file} generated...")


if __name__ == "__main__":
    title_print("Alexandria - CLI website preservation")

    parser = argparse.ArgumentParser(prog="Alexandria", description="A tool to manage your personal website backup libary", epilog="Keep and hold")
    parser.add_argument("url", help="One or more internet links (URL)", nargs="*")
    parser.add_argument("-p", "--port", help="The port to run server, 8000 is default", default=Preferences.server_port, type=int)
    parser.add_argument("-v", "--verbose", help="Enable verbose", default=Preferences.debug, action=argparse.BooleanOptionalAction, type=bool)
    parser.add_argument("-s", "--skip", help="Skip download process, only add entry.", default=False, action=argparse.BooleanOptionalAction, type=bool)
    parser.add_argument("--readme", "--database-readme", help="Generate the database README.", default=True, action=argparse.BooleanOptionalAction, type=bool)
    args = parser.parse_args()
    
    url_to_download = args.url
    pref = Preferences(library_path="./alx", server_port = args.port, debug = args.verbose, generate_readme = args.readme, skip_download=args.skip)

    database = Database(pref.db, pref.db_static, pref.readme)
    database.load()
    if pref.debug and pref.generate_readme:
        generate_md_database(database.to_md())
        sys.exit()

    # server it - bye!
    if not url_to_download:
        serve(pref)
        # sys.exit()

    if pref.skip:
        debug_print("BYPASSING THE PROCESS OF DOWNLOAD - you are on your own", border=True)
    else:
        for url in url_to_download :
            process_download(url, pref.db_static)
            webpage = WebPage(url, pref.db_static)
            database.add(webpage)

    database.save()
    generate_md_database(database.to_md(), pref.readme)
