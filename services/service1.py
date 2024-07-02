from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import yaml
import subprocess
import base64
from kubernetes import client, config
from kubernetes.client import V1StatefulSet, V1StatefulSetSpec, V1PodTemplateSpec, V1ObjectMeta, V1PodSpec, V1Container, V1Service, V1ServiceSpec, V1PersistentVolumeClaim, V1ResourceRequirements, V1VolumeMount, V1VolumeClaimTemplate


app = FastAPI()

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

@app.post("/generate-deployment/")
def generate_deployment(config: FullConfig):

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

    return {"message": "Deployment, Service, and Secret created successfully.",
            "deployment_yaml": deployment_yaml,
            "service_yaml": service_yaml,
            "secret_yaml": secret_yaml
            }

@app.post("/receiving_status_of_specific_deployment")
def get_deployment_status(appname: str):
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
        return status
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/receiving_status_of_all_deployments")
def get_all_deployment_statuses():
    try:
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
        return all_statuses
    except client.exceptions.ApiException as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/deploy-postgresql")
async def deploy_postgresql():
    try:
        # Define the PostgreSQL StatefulSet
        statefulset = V1StatefulSet(
            api_version="apps/v1",
            kind="StatefulSet",
            metadata=V1ObjectMeta(name="postgresql"),
            spec=V1StatefulSetSpec(
                service_name="postgresql",
                replicas=1,
                selector={"matchLabels": {"app": "postgresql"}},
                template=V1PodTemplateSpec(
                    metadata=V1ObjectMeta(labels={"app": "postgresql"}),
                    spec=V1PodSpec(containers=[
                        V1Container(
                            name="postgresql",
                            image="bitnami/postgresql:latest",
                            ports=[{"containerPort": 5432}],
                            env=[
                                {"name": "POSTGRESQL_USERNAME", "value": "my_user"},
                                {"name": "POSTGRESQL_PASSWORD", "value": "my_password"},
                                {"name": "POSTGRESQL_DATABASE", "value": "my_database"}
                            ],
                            volume_mounts=[V1VolumeMount(
                                name="postgresql-data",
                                mount_path="/bitnami/postgresql"
                            )]
                        )
                    ])
                ),
                volume_claim_templates=[
                    V1VolumeClaimTemplate(
                        metadata=V1ObjectMeta(name="postgresql-data"),
                        spec=V1PersistentVolumeClaim(
                            access_modes=["ReadWriteOnce"],
                            resources=V1ResourceRequirements(
                                requests={"storage": "1Gi"}
                            )
                        )
                    )
                ]
            )
        )

        # Create the StatefulSet
        k8s_apps_v1 = client.AppsV1Api()
        k8s_apps_v1.create_namespaced_stateful_set(
            namespace="default",
            body=statefulset
        )

        # Define the PostgreSQL Service
        service = V1Service(
            api_version="v1",
            kind="Service",
            metadata=V1ObjectMeta(name="postgresql"),
            spec=V1ServiceSpec(
                selector={"app": "postgresql"},
                ports=[{"port": 5432, "targetPort": 5432}]
            )
        )

        # Create the Service
        k8s_core_v1 = client.CoreV1Api()
        k8s_core_v1.create_namespaced_service(
            namespace="default",
            body=service
        )

        return {"message": "PostgreSQL StatefulSet and Service created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
