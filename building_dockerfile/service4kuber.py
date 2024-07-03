from fastapi import FastAPI, HTTPException
from kubernetes import client, config
from kubernetes.client import *
import psycopg2
from psycopg2.extras import RealDictCursor
from fastapi.responses import JSONResponse
import psycopg2
import base64
import secrets
import time
# app = FastAPI()

# Load Kubernetes configuration
config.load_incluster_config()

#@app.post("/deploy-postgresql")
def deploy_postgresql(appname, cpu, memory, external):
    try:

#################################################### SECRET #############################################
        username = secrets.token_hex(4)  # Generate a random hexadecimal username
        password = secrets.token_urlsafe(10)  # Generate a random URL-safe password    
        database = 'my_database'
        # print(f"your username is : {username}")
        # print(f"your password is : {password}")
        # Define secret data
        secret_data = {
            'POSTGRES_USER': base64.b64encode(username.encode()).decode(),
            'POSTGRES_PASSWORD': base64.b64encode(password.encode()).decode(),
            'POSTGRES_DB': base64.b64encode(database.encode()).decode()
        }

        print(f"your username is : {base64.b64encode(username.encode()).decode()}")
        print(f"your password is : {base64.b64encode(password.encode()).decode()}")
        print(f"your postgresDB : {base64.b64encode(database.encode()).decode()}")


        #Define the PostgreSQL secret
        secret = client.V1Secret(
            api_version="v1",
            kind="Secret",
            metadata=client.V1ObjectMeta(name=f"{appname}-secret"),
            type="Opaque",  # Specifies the type of the Secret
            data= secret_data
        )

        # Create the Secret
        k8s_core_v1 = client.CoreV1Api()
        k8s_core_v1.create_namespaced_secret(
            namespace="default",
            body=secret
        )
############################################ ConfigMap ##################################################
        # Define the ConfigMap object
        config_map = client.V1ConfigMap(
            api_version="v1",
            kind="ConfigMap",
            metadata=client.V1ObjectMeta(name=f"{appname}-config"),
            data={
                "postgresql.conf": """
                    # PostgreSQL configuration file
                    
                    # General settings
                    listen_addresses = '*'
                    max_connections = 100
                    
                    # Memory and performance tuning
                    shared_buffers = 128MB
                    effective_cache_size = 4GB
                    work_mem = 4MB
                    
                    # Logging
                    logging_collector = on
                    log_directory = '/var/log/postgresql'
                    log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'
                    log_statement = 'all'
                """
            }
        )

        # Create the ConfigMap
        k8s_core_v1 = client.CoreV1Api()
        k8s_core_v1.create_namespaced_config_map(
            namespace="default",
            body=config_map
        )
############################################## PV & PVC #################################################

        # Define the PersistentVolume object
        persistent_volume = client.V1PersistentVolume(
            api_version="v1",
            kind="PersistentVolume",
            metadata=client.V1ObjectMeta(name=f"{appname}-pv"),
            spec=client.V1PersistentVolumeSpec(
                capacity={"storage": "1Gi"},
                access_modes=["ReadWriteOnce"],
                host_path=client.V1HostPathVolumeSource(path="/mnt/data/postgres")
            )
        )

        # Create the PV
        k8s_core_v1 = client.CoreV1Api()
        k8s_core_v1.create_persistent_volume(
            body=persistent_volume
        )

        # Define the PersistentVolumeClaim object
        persistent_volume_claim = client.V1PersistentVolumeClaim(
            api_version="v1",
            kind="PersistentVolumeClaim",
            metadata=client.V1ObjectMeta(name=f"{appname}-pvc"),
            spec=client.V1PersistentVolumeClaimSpec(
                access_modes=["ReadWriteOnce"],
                resources=client.V1ResourceRequirements(
                    requests={"storage": "1Gi", "cpu": cpu, "memory": memory}
                )
            )
        )

        # Create the PVC
        k8s_core_v1 = client.CoreV1Api()
        k8s_core_v1.create_namespaced_persistent_volume_claim(
            namespace='default',
            body=persistent_volume_claim
        )

########################################################################################################

        # Define the PostgreSQL StatefulSet
        statefulset = V1StatefulSet(
            api_version="apps/v1",
            kind="StatefulSet",
            metadata=V1ObjectMeta(name= appname),
            spec=V1StatefulSetSpec(
                service_name="postgres",
                replicas=1,
                selector={"matchLabels": {"app": appname}},
                template=V1PodTemplateSpec(
                    metadata=V1ObjectMeta(labels={"app": appname}),
                    spec=V1PodSpec(containers=[
                        V1Container(
                            name= appname,
                            image="postgres:16.3",
                            ports=[{"containerPort": 5432}],
                            env_from=[
                                client.V1EnvFromSource(
                                config_map_ref=client.V1ConfigMapEnvSource(name=f"{appname}-config")
                                ),
                                client.V1EnvFromSource(
                                secret_ref=client.V1SecretEnvSource(name=f"{appname}-secret")
                            )],
                        )
                    ])
                ),
            )
        )

        # Create the StatefulSet
        k8s_apps_v1 = client.AppsV1Api()
        k8s_apps_v1.create_namespaced_stateful_set(
            namespace="default",
            body=statefulset
        )
        if (external == False):
        # Define the PostgreSQL Service
            service = client.V1Service(
                api_version="v1",
                kind="Service",
                metadata=client.V1ObjectMeta(name=f"{appname}-service"),
                spec=client.V1ServiceSpec(
                    ports=[
                        client.V1ServicePort(port=5432, name= appname, protocol="TCP")
                    ],
                    cluster_ip=None,
                    selector={"app": appname}
                )
            )
        
        if (external == True):
            service = client.V1Service(
            api_version="v1",
            kind="Service",
            metadata=client.V1ObjectMeta(name=f"{appname}-service"),
            spec=client.V1ServiceSpec(
                selector={"app": appname},
                ports=[client.V1ServicePort(
                    port=5432,
                    target_port=5432,
                    protocol="TCP",
                    name= appname
                )],
                type="LoadBalancer"  # Use "NodePort" if your environment does not support LoadBalancer
            )
        )


        # Create the Service
        k8s_core_v1 = client.CoreV1Api()
        k8s_core_v1.create_namespaced_service(
            namespace="default",
            body=service
        )

        # # checking for external access
        # if (external == True):
        #     initialize_postgresql(appname, username)

        return {"message": "PostgreSQL StatefulSet and Service and Secret created successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


def initialize_postgresql(appname, username):
    try:
        # Load Kubernetes configuration
        config.load_kube_config()

        # Specify the namespace and pod name (adjust these according to your deployment)
        namespace = "default"
        pod_name = f"{appname}-0"  # Adjust this according to your StatefulSet pod naming convention
        container = appname

        # Create an instance of the CoreV1Api
        api_instance = client.CoreV1Api()

        # Command to execute inside the pod (psql command)
        command = [f'psql', '-U', {username}, '-d', 'my_database']  # Replace with your PostgreSQL username and database

        # Execute shell command in the specified pod and container
        resp = api_instance.connect_get_namespaced_pod_exec(
            name=pod_name,
            namespace=namespace,
            command=command,
            container=container,
            stdin=False,  # Set stdin to False when not interactive
            stdout=True,
            stderr=True,
            tty=False,  # Set tty to False when not interactive
            _preload_content=False,
            stream=True  # Use stream=True to handle WebSocket upgrade
        )

        # Print command output
        print("Command output:")
        for line in resp:
            print(line)

    except Exception as e:
        print(f"Error executing command in pod: {str(e)}")







def get_db_connection():
    conn = psycopg2.connect(
        host="postgresql-slave.default.svc.cluster.local",  # Ensure this matches your PostgreSQL slave service name
        database="yourdatabase",
        user="mydbuser",
        password="mypassword"
    )
    return conn











# import yaml
# import base64
# import secrets
# from kubernetes import client, config

# def generate_random_values():
#     username = secrets.token_hex(4)  # Generate a random hexadecimal username
#     password = secrets.token_urlsafe(10)  # Generate a random URL-safe password
#     return username, password

# def create_update_secret(username, password):
#     config.load_kube_config()  # Load kube config from default location (e.g., ~/.kube/config)

#     v1 = client.CoreV1Api()

#     # Define secret data
#     secret_data = {
#         'username': base64.b64encode(username.encode()).decode(),
#         'password': base64.b64encode(password.encode()).decode()
#     }

#     # Create/update Kubernetes secret
#     secret_name = 'postgresql-secret'
#     namespace = 'default'
#     body = {
#         'apiVersion': 'v1',
#         'kind': 'Secret',
#         'metadata': {'name': secret_name},
#         'type': 'Opaque',
#         'data': secret_data
#     }

#     try:
#         # Check if secret exists, if not create it, otherwise update it
#         existing_secret = v1.read_namespaced_secret(name=secret_name, namespace=namespace)
#         v1.replace_namespaced_secret(name=secret_name, namespace=namespace, body=body)
#         print(f"Secret '{secret_name}' updated successfully.")
#     except client.exceptions.ApiException as e:
#         if e.status == 404:
#             v1.create_namespaced_secret(namespace=namespace, body=body)
#             print(f"Secret '{secret_name}' created successfully.")
#         else:
#             raise

# def main():
#     username, password = generate_random_values()
#     create_update_secret(username, password)

# if __name__ == "__main__":
#     main()
