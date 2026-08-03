import io
import os
import json
import logging
import hashlib
import docker
import difflib
import tarfile
import argparse
import subprocess

def long_path(path):
    """Return a path usable beyond the Windows 260-char MAX_PATH limit.

    On Windows, prefixing an absolute path with '\\\\?\\' disables MAX_PATH
    normalization so deep paths (e.g. node_modules trees) can be created.
    On other platforms the path is returned unchanged.
    """
    abs_path = os.path.abspath(path)
    if abs_path.startswith("\\\\?\\"):
        return abs_path
    return "\\\\?\\" + abs_path

class OfficePyContainer():
    dirs_to_log = ['/', '/agent', '/agent/logs', '/home', '/home/app', '/home/jovyan', '/home/nonroot', '/mnt', '/root', '/tmp', '/app', '/app/api', '/app/api/node_modules', '/app/test', '/app/node_modules', '/app/officepy', '/app/share', '/app/share/output', '/app/skills', '/officepyapp']
    filesystem_name = "filesystem.json"
    python_packages_name = "python_packages.csv"
    dotnet_dir = "ASP.NET"
    site_packages = "site_packages"
    paths_to_copy = {'/officepyapp': '',
                    '/app/containertoolservice': 'officepyapp',
                    '/app/officepy/lib/python3.12/site-packages/excel': site_packages,
                    '/app/officepy/lib/python3.12/site-packages/officepyai': site_packages,
                    '/app/api': 'node.js',
                    '/app/anthropic.env': 'node.js',
                    '/app/package.json': 'node.js',
                    '/app/version.env': 'node.js'}
    files_to_decompile = {"containeradmin": ["containeradmin"],
            "httpproxy": ["httpproxy"],
            "service": ['Microsoft.OfficePy.Core', 'Microsoft.OfficePy.DataStore.Abstractions', 'Microsoft.OfficePy.Deployment', 'Microsoft.OfficePy.JupyterServerProtocolClient.Abstractions', 'Microsoft.OfficePy.JupyterServerProtocolClient', 'Microsoft.OfficePy.MultiJupyterServerProtocolClient', 'Microsoft.OfficePy.Service.Abstractions', 'Microsoft.OfficePy.Service.CodeExecutionService', 'Microsoft.OfficePy.Service.Core', 'Microsoft.OfficePy.Service.Foundation'],
            "containertoolservice": ["Microsoft.OfficePy.Service.ContainerToolService.WebApp", "Microsoft.OfficePy.Service.ContainerToolService", "Microsoft.OfficePy.Service.CopilotClient"]}
    
    def __init__(self, client, image):
        self.client = client
        print(f"pulling {image}")
        self.docker_image = client.images.pull(image)
        self.output_dir = self._get_output_dir(image)

        if not os.path.exists(self.output_dir):
            os.mkdir(self.output_dir)

    # mcr.microsoft.com/officepy/codeexecutionjupyter4:latest -> codeexecutionjupyter4_latest_SHA256
    def _get_output_dir(self, image):
        name = image.split('/')[-1]
        base_name, version = name.split(':')
        sha256 = self.docker_image.short_id.split(':')[1]
        return f"{base_name}_{version}_{sha256}"
    
    def collect_image_info(self, ilspycmd):
        instance = self.client.containers.run(
            image=self.docker_image,
            detach=True,
            tty=True,
            remove=True
        )

        try:
            # We list all the files in directories related to the services running on the container
            image_file_system = self.get_filesystem_from_container(instance)
            with open(os.path.join(self.output_dir, OfficePyContainer.filesystem_name), 'w', encoding='utf-8') as f:
                json.dump(image_file_system, f, indent=4)

            # We list all the installed Python libraries, their path and versions
            python_libs = self.get_python_libs_from_container(instance)
            with open(os.path.join(self.output_dir, OfficePyContainer.python_packages_name), 'w', encoding='utf-8') as f:
                f.write(python_libs)

            # Copy binaries, script and config files from the container
            self.get_services_from_container(instance)

            # if the path of ilspycmd was specified, decompile the .NET binaries
            if ilspycmd:
                self.decompile_dotnet(ilspycmd)
        finally:
            instance.stop()

    def copy_to_container(self, container, src_path, dst_dir):
        stream = io.BytesIO()
        with tarfile.open(fileobj=stream, mode='w|') as tar:
            # Create a TarInfo object for the file
            info = tarfile.TarInfo(name=os.path.basename(src_path))
            with open(src_path, 'rb') as f:
                info.size = os.path.getsize(src_path)
                tar.addfile(info, f)

        # Move the stream position to the beginning
        stream.seek(0)
        
        # Upload the tar archive to the container
        container.put_archive(dst_dir, stream.getvalue())

    def copy_from_container(self, container, src_path):
        stream, _ = container.get_archive(src_path)
        fileobj = io.BytesIO(b"".join(stream))
        with tarfile.open(fileobj=fileobj) as tar:
            for member in tar.getmembers():

                f = tar.extractfile(member)
                data = f.read()
                break
        return data

    def execute_command(self, container, command):
        exec_result = container.exec_run(
            cmd=command.split(' '),
            stdout=True,
            stderr=True
        )

        output = exec_result.output.decode("utf-8")
        return output

    def get_filesystem_from_container(self, container):
        dirs = {}
        for dir_name in OfficePyContainer.dirs_to_log:

            # Running a command inside the container is faster than accessing the filesystem through the docker library
            output = self.execute_command(container, f"ls {dir_name}").rstrip('\n')
            if output.endswith('No such file or directory'):
                continue

            dirs[dir_name] = [file for file in output.split('\n') if (not file.startswith('clr-debug-pipe')) and (not file.startswith('dotnet-diagnostic-'))]
        return dirs

    def get_python_libs_from_container(self, container):

        # Running a script inside the container is faster than copying all the libraries out of the container and check their versions
        python_script = 'get_python_libs_versions.py'
        dst = '/app'
        self.copy_to_container(container, python_script, dst)
        return self.execute_command(container, f'/app/officepy/bin/python {dst}/{python_script}')

    def get_services_from_container(self, container):

        # copy only files related to the custom applications and services installed on the container
        for src_path, dst_path in OfficePyContainer.paths_to_copy.items():
            try:
                stream, _ = container.get_archive(src_path)

            # Not all of the files are in all of the images
            except docker.errors.NotFound:
                continue
            tar_bytes = io.BytesIO(b"".join(stream))
            with tarfile.open(fileobj=tar_bytes, mode="r:*") as tar:
                members = tar.getmembers()

                # tar uses '/' separators; rewrite them to the OS separator so
                # every path join tarfile performs internally (including the
                # directory attribute-fixup pass) stays consistent with the
                # '\\?\' long-path prefix, which disables '/' handling.
                for member in members:
                    member.name = member.name.replace('/', os.sep)

                tar.extractall(
                    path=long_path(os.path.join(self.output_dir, dst_path)),
                    members=members,
                )

    def decompile_dotnet(self, ilspycmd):
        dst_dir = os.path.join(self.output_dir, OfficePyContainer.dotnet_dir)
        for directory, files in OfficePyContainer.files_to_decompile.items():
            for file in files:
                path = os.path.join(self.output_dir, "officepyapp", directory, f"{file}.dll")
                if os.path.exists(path):
                    subprocess.check_output(f"{ilspycmd} {path} --project --outputdir {dst_dir}\\{file}", shell=True)

class Differ():
    
    def __init__(self, logger: logging.Logger):
        self.logger = logger

    def diff_files(self, first_file, second_file, lines_count=3):
        first_data = open(first_file, 'rb').read()
        second_data = open(second_file, 'rb').read()

        # binary files (e.g. .dll, .docx test fixtures) can't be meaningfully
        # line-diffed and would otherwise raise UnicodeDecodeError
        try:
            first_content = first_data.decode('utf-8').splitlines(keepends=True)
            second_content = second_data.decode('utf-8').splitlines(keepends=True)
        except UnicodeDecodeError:
            self.logger.info(f"binary files {first_file} and {second_file} differ")
            return

        diff = list(difflib.unified_diff(first_content, second_content,
                                            fromfile=first_file,
                                            tofile=second_file,
                                            lineterm="",
                                            n=lines_count))
        for line in diff:
            if not line.startswith("@@"):
                self.logger.info(line.rstrip('\n'))

    def compare_filesystem(self, first_dir, second_dir):
        with open(os.path.join(first_dir, OfficePyContainer.filesystem_name), 'r', encoding='utf-8') as f:
            first_filesystem = json.load(f)

        with open(os.path.join(second_dir, OfficePyContainer.filesystem_name), 'r', encoding='utf-8') as f:
            second_filesystem = json.load(f)

        for dir_name, files in first_filesystem.items():
            if dir_name not in second_filesystem:
                self.logger.info(f"directory {dir_name} is only in {first_dir}")
            else:
                for f in files:
                    if f not in second_filesystem[dir_name]:
                        self.logger.info(f"file {dir_name}/{f} is only in {first_dir}")

        for dir_name, files in second_filesystem.items():
            if dir_name not in first_filesystem:
                self.logger.info(f"directory {dir_name} is only in {second_dir}")
            else:
                for f in files:
                    if f not in first_filesystem[dir_name]:
                        self.logger.info(f"file {dir_name}/{f} is only in {second_dir}")

    def compare_python_libs_versions(self, first_dir, second_dir):
        self.diff_files(os.path.join(first_dir, OfficePyContainer.python_packages_name), os.path.join(second_dir, OfficePyContainer.python_packages_name), lines_count=0)

    def compare_dir(self, first_dir, second_dir, compare_hash=False):
        files_not_matching = []
        missing_files = []
        for root, _, files in os.walk(first_dir):
            for f in files:

                # skip files with irrelevant information
                if f.endswith('.pyc') or f.endswith('.csproj') or f.endswith('AssemblyInfo.cs'):
                    continue

                # does the file exist only in one image?
                first_path = os.path.join(root, f)
                second_path = os.path.join(second_dir, os.path.relpath(first_path, first_dir))
                if not os.path.exists(second_path):
                    missing_files.append(first_path)

                # if the file exists in both images, compare its content only if flag was set
                elif compare_hash:

                    # the namespaces create very long paths that exceed the maximum length
                    # convert the path format to avoid exception
                    long_first_path = long_path(first_path)
                    long_second_path = long_path(second_path)
                    with open(long_first_path, 'rb') as f_first, open(long_second_path, 'rb') as f_second:
                        first_data = f_first.read()
                        second_data = f_second.read()
                    first_sha256 = hashlib.sha256(first_data).hexdigest()
                    second_sha256 = hashlib.sha256(second_data).hexdigest()

                    # we want to print missing files first. mark the file for diff and to it after
                    if first_sha256 != second_sha256:
                        files_not_matching.append((first_path, second_path))

        if missing_files:
            self.logger.info(f"files in {first_dir} and not in {second_dir}")
            for missing_file in missing_files:
                self.logger.info(f'\t{missing_file}')

        if files_not_matching:
            self.logger.info(f"files not matching between {first_dir} and {second_dir}")
            for first_path, second_path in files_not_matching:
                self.diff_files(first_path, second_path)

    def compare_code(self, first_dir, second_dir, code_dir):
        first_code_dir = os.path.join(first_dir, code_dir)
        second_code_dir = os.path.join(second_dir, code_dir)

        # find files that are in the second image and not in the first image
        self.compare_dir(second_code_dir, first_code_dir)

        # find files that are in the first image and not in the second image
        # the content of files that exist in both images needs to be compared only once
        self.compare_dir(first_code_dir, second_code_dir, True)

    def compare_info(self, first_dir, second_dir):
        self.compare_filesystem(first_dir, second_dir)
        self.compare_python_libs_versions(first_dir, second_dir)
        self.compare_code(first_dir, second_dir, OfficePyContainer.dotnet_dir)
        self.compare_code(first_dir, second_dir, OfficePyContainer.site_packages)

def create_logger():
    filename = os.path.basename(__file__)
    logger = logging.getLogger(filename)
    file_handler = logging.FileHandler("compare_results.txt", mode='w', encoding='utf-8')
    logger.addHandler(file_handler)
    logger.setLevel(logging.INFO)
    return logger 

def get_args():
    parser = argparse.ArgumentParser(description="Compares two OfficePy docker images to find differences in their files and code")
    parser.add_argument("-i", "--ilspycmd", type=str, help="path to the tool ilspycmd to decompile .NET files")
    parser.add_argument("first", type=str, help="first image")
    parser.add_argument("second", type=str, help="second image")
    args = parser.parse_args()
    return args

def main():
    logger = create_logger()
    args = get_args()
    client = docker.from_env()
    first_container = OfficePyContainer(client, args.first)
    second_container = OfficePyContainer(client, args.second)
    first_container.collect_image_info(args.ilspycmd)
    second_container.collect_image_info(args.ilspycmd)
    differ = Differ(logger)
    differ.compare_info(first_container.output_dir, second_container.output_dir)
    print(f"Results written to {logger.handlers[0].baseFilename}")

if __name__ == "__main__":
    main()