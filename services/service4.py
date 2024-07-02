from fastapi import FastAPI, HTTPException
from kubernetes import client, config
from kubernetes.client import V1StatefulSet, V1StatefulSetSpec, V1PodTemplateSpec, V1ObjectMeta, V1PodSpec, V1Container, V1Service, V1ServiceSpec, V1PersistentVolumeClaim, V1ResourceRequirements, V1VolumeMount, V1VolumeClaimTemplate

app = FastAPI()

# Load Kubernetes configuration
config.load_kube_config()

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

