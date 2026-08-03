import io
import json
import socket
import docker
import tarfile
import argparse

def get_args():
    parser = argparse.ArgumentParser(description="Pull the OfficePy docker image and list all the servers in the configuration file")
    parser.add_argument("-i", "--image", help="Which docker image to extract the configuration file from", default="mcr.microsoft.com/officepy/codeexecutionjupyter:latest")
    parser.add_argument("-a", "--alive", action='store_true',  help="show only live servers")
    args = parser.parse_args()
    return args

def copy_from_container(image_name , file_path):
    client = docker.from_env()

    # Pull the newest version (download if missing)
    print(f"pulling {image_name}")
    client.images.pull(image_name)
    container = None
    data = None
    try:
        container = client.containers.create(image_name)
        stream, _ = container.get_archive(file_path)
        fileobj = io.BytesIO(b"".join(stream))
        with tarfile.open(fileobj=fileobj) as tar:
            for member in tar.getmembers():

                f = tar.extractfile(member)
                data = f.read()
                break
    finally:
        if container is not None:
            container.remove(force=True)
    return data

def parse_deployment_data_json(deployment_data):
    hostnames = set()
    deploymentJson = json.loads(deployment_data)
    locationShortNames = deploymentJson['locationShortNames']
    rings = deploymentJson['rings']
    for ringName, ringData in rings.items():
        envNames = ringData['envNames']
        for envName, envData in envNames.items():
            subscriptions = envData['subscriptions']
            subShortNames = subscriptions.keys()
            locations = envData['locations']
            for location in locations:
                location_name = location['name']
                locationShortName = locationShortNames.get(location_name, location_name)
                for subShortName in subShortNames:
                    hostnames.add(f"{envName}-{subShortName}-{locationShortName}.officepy.svc.usercontent.microsoft")
    return hostnames

def nslookup(hostname):
    try:
        ip_address = socket.gethostbyname(hostname)
        return True
    except socket.gaierror:
        return False

def main():
    args = get_args()
    deployment_data = copy_from_container(args.image, '/officepyapp/containeradmin/deploymentdata.json')
    hostnames = parse_deployment_data_json(deployment_data)
    print(f"found {len(hostnames)} hostnames in config file")
    if args.alive:
        hostnames = [host for host in hostnames if nslookup(host)]
        print(f"{len(hostnames)} online")
    for host in hostnames:
        print(host)

if __name__ == "__main__":
    main()