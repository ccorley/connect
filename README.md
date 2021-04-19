# pyConnect
LinuxForHealth Connectors for Inbound Data Processing

## Where to Contribute  
| Type      | Link |
| ----------- | ----------- |
| 🚨 Bug Reports | [GitHub Issues Tracker](https://github.com/LinuxForHealth/pyconnect/labels/bug) |  
| 🎁 Feature Requests & Ideas | [GitHub Issues Tracker](https://github.com/LinuxForHealth/pyconnect/issues)  | 
| ❔ Questions | [LFH Slack Channel](https://ibm-watsonhealth.slack.com/archives/G01639WJEMA) |   
| 🚙 Roadmap | [Project Board](https://github.com/LinuxForHealth/pyconnect/projects/1) |


## Getting Started

### Required Software
The LinuxForHealth pyConnect development environment requires the following:

- [git](https://git-scm.com) for project version control
- [mkcert](https://github.com/FiloSottile/mkcert) for local trusted certificates
- [Python 3.8 or higher](https://www.python.org/downloads/mac-osx/) for runtime/coding support
- [Poetry](https://python-poetry.org/docs/) for Python dependency management  
- [Docker Compose](https://docs.docker.com/compose/install/) for a local container runtime

For Windows 10 users, we suggest using [Windows Subsystem for Linux](https://docs.microsoft.com/en-us/windows/wsl/install-win10)

### Set Up A Local Environment
### Verify poetry installation
```shell
poetry --version
```

#### Clone the project and navigate to the root directory
```shell
git clone https://github.com/LinuxForHealth/pyconnect
cd pyconnect
```

#### Create a virtual environment
```shell
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip 
```

#### Install pyconnect wit
```shell
poetry install
# pip install -e .[dev,test]
# note if using zsh shell the extra dependencies require quoting
# pip install -e ".[dev,test]"
```

#### Generate trusted local certs for pyConnect and supporting services
```shell
./local-certs/install-certificates.sh
```
For more information on pyConnect and HTTPS/TLS support, please refer to [the local cert readme](./local-certs/README.md).


#### Start pyConnect and supporting services
```shell
docker-compose up -d
docker-compose ps

APPLICATION_CERT_PATH=./local-certs \
  UVICORN_RELOAD=True \
  python pyconnect/main.py
```

Browse to `https://localhost:5000/docs` to view the Open API documentation

### Docker Image
The pyConnect docker image is an "incubating" feature and is subject to change. The image is associated with the "deployment" profile to provide separation from core services.

#### Build the image
The pyconnect image build integrates the application's x509 certificate (PEM encoded) into the image.

The `APPLICATION_CERT_PATH` build argument is used to specify the location of the certificate on the host machine.
If the `APPLICATION_CERT_PATH` build argument is not provided, a default value of ./local-certs/lfh.pem is used.

#### Build the image with Docker CLI
```shell
docker build --build-arg APPLICATION_BUILD_CERT_PATH=./local-certs/ -t linuxforhealth/pyconnect:0.25.0 .
```

#### Build the image with Docker-Compose
The docker-compose command below parses the build context, arguments, and image tag from the docker-compose.yaml file.
```shell
docker-compose build connect
```

#### Run pyConnect and Supporting Services
```shell
docker-compose --profile deployment up -d
```

## Links and Resources 
| Type      | Link |
| ----------- | ----------- |
| 📰 Documentation | [LinuxForHealth Docs Site](https://linuxforhealth.github.io/docs/) |  
| 📰 Documentation | [IPFS](./IPFS.md) |  
