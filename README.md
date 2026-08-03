
# From square root to /root
This repository contains several tools to research the environment of Python in Excel, as presented at the talk "From square root to /root: escalating privileges in Azure containers with Python in Excel" from DEF CON 34.

## run_container.py
This tool utilizes the REST API of the servers to launch a container and execute a Python script on it
```
usage: run_container.py [-h] [-b BEARER_TOKEN] [-s SERVER] [-d DATA_FILE] -p PYTHON_SCRIPT

Launch an OfficePy container in Azure and run a Python script on it

options:
  -h, --help            show this help message and exit
  -b, --bearer-token BEARER_TOKEN
                        Bearer token of Microsoft account for authentication
  -s, --server SERVER   Request a container on a specific server
  -d, --data-file DATA_FILE
                        File to upload to the container before executing the Python script
  -p, --python-script PYTHON_SCRIPT
                        Path to the script to execute on the container
```
The bearer token of your Microsoft account can be supplied as a command line paramter, environment variable (BEARER_TOKEN) or using standard input. It can be captured by using tools like Fiddler to decrypt the HTTPS traffic sent by Excel when running a Python cell. It should look like this: `Bearer eyJ...`

Microsoft has servers all around the world for this solution. A specific one can be set. If not, the tool follows the same actions done by Excel and requests a random one from: https://service-preview.officepy.svc.usercontent.microsoft

If the Python script requires an additional file for its execution, such as an image, zip or ELF, it can be uploaded using the parameter -d. The tool utilizes the dedicated API for uploading files to the container. The environment variable `OFFICEPY_DATA_UPLOAD_PATH` points to the main directory where files are uploaded. A sub-directory with a random name is created upon the upload request and in it will be the original file under the name `upload.data`

for example:
```
/mnt/data_upload/9ff50193-3532-43e3-9425-ad41754c568a:
total 12
-rw-rw-rw- 1 root root 5 Jun 27 10:51 upload.data
-rw-r--r-- 1 root root 9 Jun 27 10:51 upload.etag
-rw-r--r-- 1 root root 5 Jun 27 10:51 upload.stat
```

## get_servers_names.py
This tool pulls the docker image used by the Python in Excel containers, extracts the configuration file of the Code Execution Service and lists all the servers that host containers. Some of the servers might not be available. To list only the live servers use the parameter `--alive`.

The default docker image used by this tool is `mcr.microsoft.com/officepy/codeexecutionjupyter`. Various images can be used:
```
mcr.microsoft.com/officeagent/officeagent:MSIT
mcr.microsoft.com/officeagent/officeagent:PPE
mcr.microsoft.com/officeagent/officeagent:Production
mcr.microsoft.com/officeagent/officeagent:Production-Canary
mcr.microsoft.com/officeagent/officeagent:Production-Pilot
mcr.microsoft.com/officeagent/officeagent:Production-Rest
mcr.microsoft.com/officepy/codeexecutionjupyter:latest
mcr.microsoft.com/officepy/codeexecutionjupyter2:latest
mcr.microsoft.com/officepy/codeexecutionjupyter3:latest
mcr.microsoft.com/officepy/codeexecutionjupyter4:latest
mcr.microsoft.com/officepy/codeexecutionjupyter5:latest
mcr.microsoft.com/officepy/codeexecutionjupyter6:latest
mcr.microsoft.com/officepy/codeexecutionjupyter7:latest
mcr.microsoft.com/officepy/codeexecutionjupyter8:latest
mcr.microsoft.com/officepy/codeexecutionjupyterext1:latest
mcr.microsoft.com/officepy/codeexecutionjupyterext2:latest
mcr.microsoft.com/officepy/codeexecutionjupyterext3:latest
mcr.microsoft.com/officepy/codeexecutionjupyterext4:latest
```
## compare_images.py
This tool compares two OfficePy Docker images to find the differences between their files and code. Useful for tracking what changed between two image versions/tags (e.g. :latest vs. a previous build).
<ol>
  <li>Filesystem - lists the files in directories where custom apps and services are installed to check if new components were added</li>
  <li>Python packages - lists all the installed Python libraries and their versions to check if they were updated or if new libraries were added</li>
  <li>Service files - copies only the custom application/service files (binaries, scripts, configs)</li>
  <li>.NET decompilation (optional) - if ilspycmd is installed and its path is specified, the .NET binaries can be decompiled to check for differences in the code</li>
</ol>

Since output might be verbose, it is written to a text file.

## Credits
* [Ron Ben Yizhak](https://x.com/RonB_Y)

## References
* [A First Look at Python in Excel](https://www.netspi.com/blog/technical-blog/red-teaming/a-first-look-at-python-in-excel)
* [The Problems of Embedded Python in Excel](https://i.blackhat.com/Asia-25/Asia-25-Carmel-The-Problems-of-Embedded-Python-in-Excel.pdf)