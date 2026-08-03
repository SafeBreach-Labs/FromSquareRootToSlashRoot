import os
import logging
import argparse
from OfficePy import OfficePy

def create_logger():
    filename = os.path.basename(__file__)
    logger = logging.getLogger(filename)
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)
    return logger 

def get_args():
    parser = argparse.ArgumentParser(description="Launch an OfficePy container in Azure and run a Python script on it")
    parser.add_argument("-b", "--bearer-token", help="Bearer token of Microsoft account for authentication")
    parser.add_argument("-s", "--server", help="Request a container on a specific server")
    parser.add_argument("-d", "--data-file", help="File to upload to the container before executing the Python script")
    parser.add_argument("-p", "--python-script", required=True, help="Path to the script to execute on the container")
    args = parser.parse_args()
    return args

def main():
    try:
        logger = create_logger()
        args = get_args()
        if args.bearer_token is not None:
            bearer_token = args.bearer_token
        elif 'BEARER_TOKEN' in os.environ:
            bearer_token = os.environ['BEARER_TOKEN']
        else:
            bearer_token = input("Enter bearer token: ")
        container = OfficePy(args.server, bearer_token, logger)
        container.execute_script(args.python_script, args.data_file)
    except Exception as ex:
        print(ex)

if __name__ == "__main__":
    main()