import os
import uuid
import time
import json
import logging
import requests

requests.packages.urllib3.disable_warnings(requests.packages.urllib3.exceptions.InsecureRequestWarning)

class OfficePy():
    data_id = "upload"
    etag = "etag_data"
    max_timeout = 1700

    def __init__(self, hostname: str, token: str, logger: logging.Logger):
        self.headers = {"Authorization": token}
        self.logger = logger
        self.environment_id = ''

        # If no server was specified by the client, request a random one from Microsoft
        if hostname is None:
            hostname = self._request_hostname()
        self.hostname = hostname
        self.address = f"https://{hostname}"
        self._get_identifications()

    def __del__(self):

        # if the destructor was called before an environment was initialized, do nothing
        if not self.environment_id:
            return
        
        # send the same requests as Excel when a document is closed
        url = f"{self.address}/api/environments/{self.environment_id}/runtimes/{self.runtime_id}"
        response = requests.delete(url, headers=self.headers, verify=False)
        if response.status_code != 204:
            raise Exception(f"{response.status_code} {url}\n{response.text}")
        
        endpoint = f"/api/environments/{self.environment_id}/closeconnection"
        self._send_request(endpoint, params={"connectionId": self.connection_id}, post=True, expected_status=204)

    def _send_request(self, endpoint: str, params=None, json_data=None, files=None, post=False, expected_status=200):
        url = f"{self.address}{endpoint}"
        if post:
            response = requests.post(url, params=params, headers=self.headers, verify=False, json=json_data, files=files)
        else:
            response = requests.get(url, params=params, headers=self.headers, verify=False, json=json_data)

        # sometimes the body of the response contains details about why the request failed
        if response.status_code != expected_status:
            raise Exception(f"{response.status_code} {url}\n{response.text}")
        
        # serialize body into json when the content type specifies it or return a string otherwise
        if 'application/json' in response.headers.get('Content-Type', ''):
            body = response.json()
        else:
            body = response.text
        return body
    
    def _request_hostname(self):
        self.address = "https://service-preview.officepy.svc.usercontent.microsoft"
        response = self._send_request("/", post=True, expected_status=201)
        return response['url'].replace('https://', '')

    def _get_identifications(self):

        # initialize a new environment in the container
        connection_id = str(uuid.uuid4())

        # send only the minimal parameters for the request
        # More properties available for Microsoft.OfficePy.Service.DataTransferObject.CreateEnvironmentRequest
        request_data = {"connectionId": connection_id}
        endpoint = f"/api/environments/createenvironmentandruntime"
        response = self._send_request(endpoint, json_data=request_data, post=True, expected_status=201)

        # the environment and runtime IDs represent the exact container instance we are running on
        self.environment_id = response["id"]
        self.runtime_id = response["runtimeId"]

        # the connection ID we generated will be used to close the connection
        self.connection_id = connection_id
        self.logger.debug("environment created")
    
    def _resolve_next_url(self, next_page_url: str):
        return self._send_request(next_page_url)
    
    def _start_upload(self):
        endpoint = f"/api/environments/{self.environment_id}/runtimes/{self.runtime_id}/data/start"
        self._send_request(endpoint, params={"dataId": OfficePy.data_id, "etag": OfficePy.etag}, post=True)

    def _send_upload_data(self, data):
        endpoint = f"/api/environments/{self.environment_id}/runtimes/{self.runtime_id}/data/upload"

        # Chunk size has to be less than 2MB
        chunk_size = 1024*2047
        for i in range(0, len(data), chunk_size):
            chunk = data[i:i + chunk_size]
            files = {"data": ("data.bin", chunk, "application/octet-stream")}
            self._send_request(endpoint, params={"dataId": OfficePy.data_id}, files=files, post=True)

    def _finish_upload(self):
        endpoint = f"/api/environments/{self.environment_id}/runtimes/{self.runtime_id}/data/finish"
        return self._send_request(endpoint, params={"dataId": OfficePy.data_id}, post=True)
    
    def _upload_file(self, path):
        data = open(path, 'rb').read()
        self._start_upload()
        self._send_upload_data(data)
        upload_response = self._finish_upload()
        self.logger.debug(f"upload size: {upload_response['size']}")
        self.logger.debug(f"upload sha256Hash: {upload_response['sha256Hash']}")

    def execute_script(self, script_path: str, upload_file=None):
        script_name = os.path.basename(script_path)
        code = open(script_path, 'r').read()

        endpoint = f"/api/environments/{self.environment_id}/runtimes/{self.runtime_id}/batchexecute"

        # send only the minimal parameters for the request
        # More properties available for Microsoft.OfficePy.Service.DataTransferObject.ExecuteCodeRequest
        request_data = {"items":[{"code": code, "timeoutSeconds": OfficePy.max_timeout}]}

        # upload to the container the file requested by the client
        if upload_file:
            self._upload_file(upload_file)
            
        response = self._send_request(endpoint, json_data=request_data, post=True)

        # If the code takes time to execute, we need to wait until the response doesn't specify a value for nextPageUrl
        nextUrlCount = 1
        while response["nextPageUrl"] != None:
            self.logger.debug(f"NextUrl Count: {nextUrlCount}")
            nextPageUrl = response["nextPageUrl"]
            time.sleep(response["nextPageWaitSeconds"])
            response = self._resolve_next_url(nextPageUrl)
            nextUrlCount += 1

        # log exceptions thrown by the python code in the container
        if response['items'][0]['hresult'] != 0:
            with open(f'{self.hostname}-error.json', 'w') as outputFile:
                json.dump(response, outputFile, indent=4)
            raise Exception(f"{script_name} failed " + response['items'][0]['error_message'])
        
        self.logger.info("result:")
        self.logger.info(response['items'][0]['result'])
        self.logger.info("stdout:")
        self.logger.info(response['items'][0]['stdout'])
        return response