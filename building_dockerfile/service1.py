from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yaml
import subprocess
import base64
from kubernetes import client, config
from prometheus_client import start_http_server, Summary, Counter
from service4kuber import deploy_postgresql, get_db_connection
from psycopg2.extras import RealDictCursor
from fastapi.responses import JSONResponse
import time
app = FastAPI()

number_of_requests =  Counter("num_of_requests", "total number of requeests")

number_of_failed_requests = Counter("num_of__failed_requests", "total number of failed requeests")

request_processing_time = Summary("request_processing_time", "request process time")

number_of_db_errors = Counter("number_of_db_errors", "total number of database errors")

db_response_time = Summary("db_response_time","database response time")
# Load Kubernetes configuration
config.load_kube_config()

class DeploymentConfig(BaseModel):
    appname: str
    replicas: int
    imageaddress: str
    imagetag: str
    container_port: int
    memory_request: str
    cpu_request: str
    env_vars: dict
    secret_name: str

class ServiceConfig(BaseModel):
    name: str
    app: str
    external_access: str
    node_port: int

class SecretConfig(BaseModel):
    name: str
    # namespace: str
    data: dict

class FullConfig(BaseModel):
    deployment: DeploymentConfig
    service: ServiceConfig
    secret: SecretConfig

class PostgresConfig(BaseModel):
    appname: str
    cpu: str
    memory: str
    external: bool
@request_processing_time.time()
@app.post("/generate-deployment/")
def generate_deployment(config: FullConfig):
    number_of_requests.inc()
    t1 = time.time()
    try:

        deployment = {
            'apiVersion': 'apps/v1',
            'kind': 'Deployment',
            'metadata': {
                'name': config.deployment.appname
            },
            'spec': {
                'replicas': config.deployment.replicas,
                'selector': {
                    'matchLabels': {
                        'app': config.deployment.appname
                    }
                },
                'template': {
                    'metadata': {
                        'labels': {
                            'app': config.deployment.appname
                        }
                    },
                    'spec': {
                        'containers': [
                            {
                                'name': config.deployment.appname,
                                'image': f"{config.deployment.imageaddress}:{config.deployment.imagetag}",
                                'ports': [
                                    {'containerPort': config.deployment.container_port}
                                ],
                                'resources': {
                                    'requests': {
                                        'memory': config.deployment.memory_request,
                                        'cpu': config.deployment.cpu_request
                                    },
                                },
                                'env': [
                                    {'name': k, 'value': v} for k, v in config.deployment.env_vars.items()
                                ],
                                'volumeMounts': [
                                    {
                                        'name': 'secret-volume',
                                        'mountPath': '/etc/secrets'
                                    }
                                ]
                            }
                        ],
                        'volumes': [
                            {
                                'name': 'secret-volume',
                                'secret': {
                                    'secretName': config.deployment.secret_name
                                }
                            }
                        ]
                    }
                }
            }
        }

        # Service YAML
        service = {
            'apiVersion': 'v1',
            'kind': 'Service',
            'metadata': {
                'name': config.service.name
            },
            'spec': {
                'selector': {
                    'app': config.deployment.appname
                },
                'type': config.service.external_access,
                'ports': [
                    {
                        'protocol': 'TCP',
                        'port': config.deployment.container_port,
                        'targetPort': config.deployment.container_port,
                        'nodePort': config.service.node_port
                    }
                ]
            }
        }

        # Secret YAML
        encoded_data = {k: base64.b64encode(v.encode()).decode() for k, v in config.secret.data.items()}
        secret = {
            'apiVersion': 'v1',
            'kind': 'Secret',
            'metadata': {
                'name': config.secret.name,
                'namespace': "default"
            },
            'data': encoded_data,
            'type': 'Opaque'
        }

        # Generate the YAML content
        deployment_yaml = yaml.dump(deployment, default_flow_style=False)
        service_yaml = yaml.dump(service, default_flow_style=False)
        secret_yaml = yaml.dump(secret, default_flow_style=False)

        # Save the YAML content to files
        deployment_filename = f"{config.deployment.appname}-deployment.yaml"
        service_filename = f"{config.service.name}.yaml"
        secret_filename = f"{config.secret.name}-secret.yaml"

        with open(deployment_filename, 'w') as file:
            file.write(deployment_yaml)
        
        with open(service_filename, 'w') as file:
            file.write(service_yaml)

        with open(secret_filename, 'w') as file:
            file.write(secret_yaml)

        # Apply the YAML files using kubectl
        subprocess.run(["kubectl", "apply", "-f", deployment_filename], check=True)
        subprocess.run(["kubectl", "apply", "-f", service_filename], check=True)
        subprocess.run(["kubectl", "apply", "-f", secret_filename], check=True)
        t2 = time.time()
        request_processing_time.observe(t2-t1)
        return {"message": "Deployment, Service, and Secret created successfully.",
                "deployment_yaml": deployment_yaml,
                "service_yaml": service_yaml,
                "secret_yaml": secret_yaml
                }
    except Exception as e:
        t2 = time.time()
        request_processing_time.observe(t2-t1)
        number_of_failed_requests.inc()
        raise HTTPException(status_code=500, detail=str(e))

@request_processing_time.time()
@app.post("/receiving_status_of_specific_deployment")
def get_deployment_status(appname: str):
    number_of_requests.inc()
    t1 = time.time()
    try:

        # Load kube config to authenticate
        config.load_kube_config()
        
        # Initialize API clients
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        
        # Read the specified deployment
        deployment = apps_v1.read_namespaced_deployment(appname, "default")
        
        # List pods with the specified label selector
        pods = core_v1.list_namespaced_pod("default", label_selector=f"app={appname}")
        
        # Prepare the status dictionary
        status = {
            "deployment": {
                "name": deployment.metadata.name,
                "replicas": deployment.spec.replicas,
                "available_replicas": deployment.status.available_replicas
            },
            "pods": []
        }
        
        # Append pod details to the status dictionary
        for pod in pods.items:
            status["pods"].append({
                "name": pod.metadata.name,
                "status": pod.status.phase,
                "node_name": pod.spec.node_name,
                "start_time": pod.status.start_time.isoformat() if pod.status.start_time else None,
                "host_ip": pod.status.host_ip,
                "pod_ip": pod.status.pod_ip
            })
        
        # Return the final status
        t2 = time.time()
        request_processing_time.observe(t2-t1)
        return status
    except client.exceptions.ApiException as e:
        t2 = time.time()
        request_processing_time.observe(t2-t1)
        number_of_failed_requests.inc()
        raise HTTPException(status_code=500, detail=str(e))

@request_processing_time.time()
@app.get("/receiving_status_of_all_deployments")
def get_all_deployment_statuses():
    number_of_requests.inc()
    t1 = time.time()
    try:
        t1 = time.time()
        # Load kube config to authenticate
        config.load_kube_config()
        
        # Initialize API clients
        apps_v1 = client.AppsV1Api()
        core_v1 = client.CoreV1Api()
        
        # List all deployments in the specified namespace
        deployments = apps_v1.list_namespaced_deployment("default")
        
        # Prepare the status dictionary
        all_statuses = []
        
        # Iterate over each deployment
        for deployment in deployments.items:
            deployment_name = deployment.metadata.name
            
            # List pods with the specified label selector
            pods = core_v1.list_namespaced_pod("default", label_selector=f"app={deployment_name}")
            
            # Prepare the status dictionary for this deployment
            status = {
                "deployment": {
                    "name": deployment_name,
                    "replicas": deployment.spec.replicas,
                    "available_replicas": deployment.status.available_replicas
                },
                "pods": []
            }
            
            # Append pod details to the status dictionary
            for pod in pods.items:
                pod_status = {
                    "name": pod.metadata.name,
                    "status": pod.status.phase,
                    "node_name": pod.spec.node_name,
                    "start_time": pod.status.start_time.isoformat() if pod.status.start_time else None,
                    "host_ip": pod.status.host_ip,
                    "pod_ip": pod.status.pod_ip
                }
                status["pods"].append(pod_status)
            
            # Append the status of this deployment to the list of all statuses
            all_statuses.append(status)
        
        # Return the final statuses
        t2 = time.time()
        request_processing_time.observe(t2-t1)
        return all_statuses
    except client.exceptions.ApiException as e:
        t2 = time.time()
        request_processing_time.observe(t2-t1)
        number_of_failed_requests.inc()
        raise HTTPException(status_code=500, detail=str(e))

@request_processing_time.time()
@app.post("/deploy-postgresql")
async def deploy_postgres(appname: str, cpu: str, memory: str, external: bool):

    number_of_requests.inc()
    t1 = time.time()
    try:

       response = deploy_postgresql(appname, cpu, memory, external)
       t2 = time.time()
       request_processing_time.observe(t2-t1)
       return response
    except Exception as e:
        t2 = time.time()
        request_processing_time.observe(t2-t1)
        number_of_failed_requests.inc()
        raise HTTPException(status_code=500, detail=str(e))

@app.get('/health/{app_name}')
async def get_health(app_name: str):
    try:
        conn = get_db_connection()
        cur = conn.cursor(cursor_factory=RealDictCursor)
        t1 = time.time() #in
        cur.execute('SELECT * FROM health_status WHERE app_name = %s', (app_name,))
        health_status = cur.fetchall()
        t2 = time.time # in
        db_response_time.observe(t2-t1) #in
        cur.close()
        conn.close()
        if not health_status:
            number_of_db_errors.inc() #in
            raise HTTPException(status_code=404, detail="App not found")
        return JSONResponse(content=health_status)
    except Exception as e:
        number_of_db_errors.inc() #in
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    start_http_server(6969)
    uvicorn.run(app, host="0.0.0.0", port=7001)

