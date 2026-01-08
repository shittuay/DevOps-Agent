"""Google Cloud Platform tools for DevOps Agent."""
import os
from typing import Dict, Any, List, Optional
from ..utils import get_logger

logger = get_logger(__name__)


def _get_gcp_client(service_type: str, project_id: Optional[str] = None):
    """
    Get GCP client for specified service.

    Args:
        service_type: Type of GCP service
        project_id: GCP project ID

    Returns:
        GCP client instance
    """
    try:
        import os
        from google.cloud import compute_v1, storage, container_v1, sql_v1, monitoring_v3

        if project_id is None:
            project_id = os.environ.get('GCP_PROJECT_ID')
            if not project_id:
                raise Exception("GCP_PROJECT_ID not found in environment variables")

        clients = {
            'compute': compute_v1.InstancesClient(),
            'storage': storage.Client(project=project_id),
            'container': container_v1.ClusterManagerClient(),
            'sql': sql_v1.SqlInstancesServiceClient(),
            'monitoring': monitoring_v3.MetricServiceClient()
        }

        return clients.get(service_type), project_id
    except ImportError:
        raise Exception("Google Cloud SDK not installed. Install with: pip install google-cloud-compute google-cloud-storage google-cloud-container google-cloud-sql google-cloud-monitoring")
    except Exception as e:
        raise Exception(f"Failed to create GCP client: {str(e)}")


def list_compute_instances(
    project_id: Optional[str] = None,
    zone: Optional[str] = None
) -> Dict[str, Any]:
    """
    List Google Compute Engine instances.

    Args:
        project_id: GCP project ID
        zone: GCP zone (e.g., 'us-central1-a')

    Returns:
        Dictionary with instance information
    """
    try:
        from google.cloud import compute_v1

        client, proj_id = _get_gcp_client('compute', project_id)

        instances = []

        if zone:
            # List instances in specific zone
            request = compute_v1.ListInstancesRequest(
                project=proj_id,
                zone=zone
            )
            instance_list = client.list(request=request)

            for instance in instance_list:
                instances.append(_format_gce_instance(instance, zone))
        else:
            # List instances in all zones
            zones_client = compute_v1.ZonesClient()
            zones_request = compute_v1.ListZonesRequest(project=proj_id)

            for zone_info in zones_client.list(request=zones_request):
                request = compute_v1.ListInstancesRequest(
                    project=proj_id,
                    zone=zone_info.name
                )
                for instance in client.list(request=request):
                    instances.append(_format_gce_instance(instance, zone_info.name))

        return {
            'success': True,
            'project': proj_id,
            'count': len(instances),
            'instances': instances
        }
    except Exception as e:
        logger.error(f"Error listing GCE instances: {str(e)}")
        return {'success': False, 'error': str(e)}


def _format_gce_instance(instance, zone: str) -> Dict[str, Any]:
    """Format GCE instance data."""
    return {
        'name': instance.name,
        'id': instance.id,
        'zone': zone,
        'machine_type': instance.machine_type.split('/')[-1],
        'status': instance.status,
        'internal_ip': instance.network_interfaces[0].network_i_p if instance.network_interfaces else None,
        'external_ip': instance.network_interfaces[0].access_configs[0].nat_i_p if instance.network_interfaces and instance.network_interfaces[0].access_configs else None,
        'tags': list(instance.tags.items) if instance.tags else [],
        'labels': dict(instance.labels) if instance.labels else {}
    }


def manage_compute_instance(
    instance_name: str,
    zone: str,
    action: str,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Manage GCE instance (start, stop, reset).

    Args:
        instance_name: Instance name
        zone: GCP zone
        action: Action to perform (start, stop, reset)
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from google.cloud import compute_v1

        client, proj_id = _get_gcp_client('compute', project_id)

        if action == 'start':
            request = compute_v1.StartInstanceRequest(
                project=proj_id,
                zone=zone,
                instance=instance_name
            )
            operation = client.start(request=request)
        elif action == 'stop':
            request = compute_v1.StopInstanceRequest(
                project=proj_id,
                zone=zone,
                instance=instance_name
            )
            operation = client.stop(request=request)
        elif action == 'reset':
            request = compute_v1.ResetInstanceRequest(
                project=proj_id,
                zone=zone,
                instance=instance_name
            )
            operation = client.reset(request=request)
        else:
            return {'success': False, 'error': f'Invalid action: {action}'}

        return {
            'success': True,
            'message': f'Instance {instance_name} {action} operation initiated',
            'project': proj_id,
            'zone': zone,
            'instance': instance_name,
            'action': action
        }
    except Exception as e:
        logger.error(f"Error managing GCE instance: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_storage_buckets(project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List Google Cloud Storage buckets.

    Args:
        project_id: GCP project ID

    Returns:
        Dictionary with bucket information
    """
    try:
        client, proj_id = _get_gcp_client('storage', project_id)

        buckets = []
        for bucket in client.list_buckets():
            buckets.append({
                'name': bucket.name,
                'location': bucket.location,
                'storage_class': bucket.storage_class,
                'time_created': bucket.time_created.isoformat() if bucket.time_created else None,
                'size_bytes': bucket.size if hasattr(bucket, 'size') else None,
                'labels': dict(bucket.labels) if bucket.labels else {}
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(buckets),
            'buckets': buckets
        }
    except Exception as e:
        logger.error(f"Error listing GCS buckets: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_gke_clusters(
    project_id: Optional[str] = None,
    location: str = '-'
) -> Dict[str, Any]:
    """
    List Google Kubernetes Engine clusters.

    Args:
        project_id: GCP project ID
        location: GCP location (zone or region, use '-' for all)

    Returns:
        Dictionary with cluster information
    """
    try:
        from google.cloud import container_v1

        client, proj_id = _get_gcp_client('container', project_id)

        parent = f"projects/{proj_id}/locations/{location}"
        request = container_v1.ListClustersRequest(parent=parent)

        response = client.list_clusters(request=request)

        clusters = []
        for cluster in response.clusters:
            clusters.append({
                'name': cluster.name,
                'location': cluster.location,
                'status': container_v1.Cluster.Status(cluster.status).name,
                'node_count': cluster.current_node_count,
                'master_version': cluster.current_master_version,
                'node_version': cluster.current_node_version,
                'endpoint': cluster.endpoint,
                'network': cluster.network,
                'subnetwork': cluster.subnetwork,
                'labels': dict(cluster.resource_labels) if cluster.resource_labels else {}
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(clusters),
            'clusters': clusters
        }
    except Exception as e:
        logger.error(f"Error listing GKE clusters: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_cloud_sql_instances(project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List Cloud SQL instances.

    Args:
        project_id: GCP project ID

    Returns:
        Dictionary with SQL instance information
    """
    try:
        from google.cloud import sql_v1

        client, proj_id = _get_gcp_client('sql', project_id)

        request = sql_v1.ListRequest(project=proj_id)
        response = client.list(request=request)

        instances = []
        for instance in response.items:
            instances.append({
                'name': instance.name,
                'database_version': instance.database_version,
                'state': sql_v1.DatabaseInstance.SqlInstanceState(instance.state).name,
                'region': instance.region,
                'tier': instance.settings.tier if instance.settings else None,
                'ip_addresses': [
                    {'type': ip.type_.name, 'ip_address': ip.ip_address}
                    for ip in instance.ip_addresses
                ] if instance.ip_addresses else [],
                'connection_name': instance.connection_name
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(instances),
            'sql_instances': instances
        }
    except Exception as e:
        logger.error(f"Error listing Cloud SQL instances: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_gcp_metrics(
    project_id: Optional[str] = None,
    metric_type: str = 'compute.googleapis.com/instance/cpu/utilization',
    resource_type: str = 'gce_instance',
    hours: int = 1
) -> Dict[str, Any]:
    """
    Get GCP metrics from Cloud Monitoring.

    Args:
        project_id: GCP project ID
        metric_type: Metric type to query
        resource_type: Resource type
        hours: Number of hours of historical data

    Returns:
        Dictionary with metrics data
    """
    try:
        from google.cloud import monitoring_v3
        from google.protobuf import duration_pb2
        from datetime import datetime, timedelta

        client, proj_id = _get_gcp_client('monitoring', project_id)

        project_name = f"projects/{proj_id}"

        # Set time interval
        now = datetime.utcnow()
        interval = monitoring_v3.TimeInterval(
            {
                "end_time": {"seconds": int(now.timestamp())},
                "start_time": {"seconds": int((now - timedelta(hours=hours)).timestamp())},
            }
        )

        # Build request
        request = monitoring_v3.ListTimeSeriesRequest(
            name=project_name,
            filter=f'metric.type="{metric_type}" AND resource.type="{resource_type}"',
            interval=interval,
            view=monitoring_v3.ListTimeSeriesRequest.TimeSeriesView.FULL,
        )

        results = client.list_time_series(request=request)

        metrics_data = []
        for result in results:
            points = []
            for point in result.points:
                points.append({
                    'timestamp': point.interval.end_time.isoformat(),
                    'value': point.value.double_value or point.value.int64_value
                })

            metrics_data.append({
                'metric': result.metric.type,
                'resource': result.resource.type,
                'labels': dict(result.metric.labels),
                'resource_labels': dict(result.resource.labels),
                'points': points
            })

        return {
            'success': True,
            'project': proj_id,
            'metric_type': metric_type,
            'count': len(metrics_data),
            'metrics': metrics_data
        }
    except Exception as e:
        logger.error(f"Error getting GCP metrics: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_cloud_functions(project_id: Optional[str] = None, location: str = '-') -> Dict[str, Any]:
    """
    List Cloud Functions.

    Args:
        project_id: GCP project ID
        location: GCP location (use '-' for all locations)

    Returns:
        Dictionary with Cloud Functions information
    """
    try:
        from google.cloud import functions_v1

        client = functions_v1.CloudFunctionsServiceClient()
        _, proj_id = _get_gcp_client('storage', project_id)

        parent = f"projects/{proj_id}/locations/{location}"
        request = functions_v1.ListFunctionsRequest(parent=parent)

        functions = []
        for function in client.list_functions(request=request):
            functions.append({
                'name': function.name.split('/')[-1],
                'status': functions_v1.CloudFunction.Status(function.status).name,
                'entry_point': function.entry_point,
                'runtime': function.runtime,
                'timeout': f"{function.timeout.seconds}s" if function.timeout else None,
                'available_memory_mb': function.available_memory_mb,
                'trigger': 'HTTP' if function.https_trigger else 'Event',
                'labels': dict(function.labels) if function.labels else {}
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(functions),
            'functions': functions
        }
    except Exception as e:
        logger.error(f"Error listing Cloud Functions: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== CREATE OPERATIONS ====================


def create_compute_instance(
    instance_name: str,
    zone: str,
    machine_type: str = 'e2-medium',
    image_project: str = 'debian-cloud',
    image_family: str = 'debian-11',
    disk_size_gb: int = 10,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new Google Compute Engine instance.

    Args:
        instance_name: Name for the instance
        zone: Zone (e.g., us-central1-a, us-west1-b)
        machine_type: Machine type (e.g., e2-medium, n1-standard-1, n2-standard-2)
        image_project: Image project (default: debian-cloud)
        image_family: Image family (default: debian-11)
        disk_size_gb: Boot disk size in GB (default: 10)
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from google.cloud import compute_v1

        instances_client = compute_v1.InstancesClient()
        proj_id = project_id or os.environ.get('GCP_PROJECT_ID')

        if not proj_id:
            raise Exception("GCP_PROJECT_ID not found")

        # Get the latest image
        images_client = compute_v1.ImagesClient()
        image = images_client.get_from_family(project=image_project, family=image_family)

        # Configure the instance
        machine_type_full = f"zones/{zone}/machineTypes/{machine_type}"

        instance = compute_v1.Instance()
        instance.name = instance_name
        instance.machine_type = machine_type_full

        # Boot disk
        disk = compute_v1.AttachedDisk()
        initialize_params = compute_v1.AttachedDiskInitializeParams()
        initialize_params.source_image = image.self_link
        initialize_params.disk_size_gb = disk_size_gb
        disk.initialize_params = initialize_params
        disk.auto_delete = True
        disk.boot = True
        instance.disks = [disk]

        # Network interface
        network_interface = compute_v1.NetworkInterface()
        network_interface.name = "global/networks/default"
        access_config = compute_v1.AccessConfig()
        access_config.name = "External NAT"
        access_config.type_ = compute_v1.AccessConfig.Type.ONE_TO_ONE_NAT.name
        network_interface.access_configs = [access_config]
        instance.network_interfaces = [network_interface]

        # Create the instance
        operation = instances_client.insert(
            project=proj_id,
            zone=zone,
            instance_resource=instance
        )

        return {
            'success': True,
            'instance_name': instance_name,
            'zone': zone,
            'machine_type': machine_type,
            'project': proj_id,
            'operation': operation.name,
            'message': f'Successfully initiated creation of instance {instance_name}. This may take a few minutes.'
        }
    except Exception as e:
        logger.error(f"Error creating GCE instance: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_storage_bucket(
    bucket_name: str,
    location: str = 'US',
    storage_class: str = 'STANDARD',
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new Google Cloud Storage bucket.

    Args:
        bucket_name: Bucket name (must be globally unique)
        location: Location (e.g., US, EU, us-central1)
        storage_class: Storage class (STANDARD, NEARLINE, COLDLINE, ARCHIVE)
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from google.cloud import storage

        client, proj_id = _get_gcp_client('storage', project_id)

        bucket = client.bucket(bucket_name)
        bucket.storage_class = storage_class

        new_bucket = client.create_bucket(bucket, location=location)

        return {
            'success': True,
            'bucket_name': new_bucket.name,
            'location': new_bucket.location,
            'storage_class': new_bucket.storage_class,
            'project': proj_id,
            'self_link': new_bucket.self_link,
            'message': f'Successfully created Cloud Storage bucket {new_bucket.name}'
        }
    except Exception as e:
        logger.error(f"Error creating Cloud Storage bucket: {str(e)}")
        return {'success': False, 'error': str(e)}


def create_cloud_sql_instance(
    instance_name: str,
    database_version: str = 'MYSQL_8_0',
    tier: str = 'db-f1-micro',
    region: str = 'us-central1',
    root_password: Optional[str] = None,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Create a new Cloud SQL instance.

    Args:
        instance_name: Instance name
        database_version: Database version (MYSQL_8_0, POSTGRES_14, SQLSERVER_2019_STANDARD)
        tier: Machine tier (db-f1-micro, db-n1-standard-1, db-n1-standard-2)
        region: Region (e.g., us-central1, us-east1, europe-west1)
        root_password: Root user password (optional, will be auto-generated if not provided)
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from googleapiclient import discovery
        from google.oauth2 import service_account
        import google.auth

        proj_id = project_id or os.environ.get('GCP_PROJECT_ID')
        if not proj_id:
            raise Exception("GCP_PROJECT_ID not found")

        credentials, _ = google.auth.default()
        sqladmin = discovery.build('sqladmin', 'v1beta4', credentials=credentials)

        instance_body = {
            'name': instance_name,
            'region': region,
            'databaseVersion': database_version,
            'settings': {
                'tier': tier,
                'backupConfiguration': {
                    'enabled': True,
                    'startTime': '03:00'
                },
                'ipConfiguration': {
                    'ipv4Enabled': True
                }
            }
        }

        if root_password:
            instance_body['rootPassword'] = root_password

        operation = sqladmin.instances().insert(
            project=proj_id,
            body=instance_body
        ).execute()

        return {
            'success': True,
            'instance_name': instance_name,
            'database_version': database_version,
            'tier': tier,
            'region': region,
            'project': proj_id,
            'operation': operation.get('name'),
            'message': f'Successfully initiated creation of Cloud SQL instance {instance_name}. This may take several minutes.'
        }
    except Exception as e:
        logger.error(f"Error creating Cloud SQL instance: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_compute_instance(
    instance_name: str,
    zone: str,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete a Google Compute Engine instance.

    Args:
        instance_name: Instance name
        zone: Zone where instance is located
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from google.cloud import compute_v1

        instances_client = compute_v1.InstancesClient()
        proj_id = project_id or os.environ.get('GCP_PROJECT_ID')

        if not proj_id:
            raise Exception("GCP_PROJECT_ID not found")

        operation = instances_client.delete(
            project=proj_id,
            zone=zone,
            instance=instance_name
        )

        return {
            'success': True,
            'instance_name': instance_name,
            'zone': zone,
            'project': proj_id,
            'operation': operation.name,
            'message': f'Successfully deleted instance {instance_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting GCE instance: {str(e)}")
        return {'success': False, 'error': str(e)}


def delete_storage_bucket(
    bucket_name: str,
    force: bool = False,
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Delete a Google Cloud Storage bucket.

    Args:
        bucket_name: Bucket name
        force: If True, delete all objects first
        project_id: GCP project ID

    Returns:
        Dictionary with operation result
    """
    try:
        from google.cloud import storage

        client, proj_id = _get_gcp_client('storage', project_id)

        bucket = client.bucket(bucket_name)

        if force:
            # Delete all blobs
            blobs = bucket.list_blobs()
            for blob in blobs:
                blob.delete()

        bucket.delete()

        return {
            'success': True,
            'bucket_name': bucket_name,
            'project': proj_id,
            'message': f'Successfully deleted Cloud Storage bucket {bucket_name}'
        }
    except Exception as e:
        logger.error(f"Error deleting Cloud Storage bucket: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_cloud_run_services(
    project_id: Optional[str] = None,
    region: str = 'us-central1'
) -> Dict[str, Any]:
    """
    List Cloud Run services.

    Args:
        project_id: GCP project ID
        region: GCP region (default: us-central1)

    Returns:
        Dictionary with Cloud Run services information
    """
    try:
        from google.cloud import run_v2

        client = run_v2.ServicesClient()
        proj_id = project_id or os.environ.get('GCP_PROJECT_ID')

        if not proj_id:
            raise Exception("GCP_PROJECT_ID not found")

        parent = f"projects/{proj_id}/locations/{region}"
        request = run_v2.ListServicesRequest(parent=parent)

        services = []
        for service in client.list_services(request=request):
            services.append({
                'name': service.name.split('/')[-1],
                'uri': service.uri,
                'description': service.description,
                'labels': dict(service.labels) if service.labels else {},
                'generation': service.generation,
                'conditions': [
                    {'type': c.type_, 'status': c.state.name}
                    for c in service.conditions
                ] if service.conditions else []
            })

        return {
            'success': True,
            'project': proj_id,
            'region': region,
            'count': len(services),
            'services': services
        }
    except Exception as e:
        logger.error(f"Error listing Cloud Run services: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_pubsub_topics(project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List Pub/Sub topics.

    Args:
        project_id: GCP project ID

    Returns:
        Dictionary with Pub/Sub topics information
    """
    try:
        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
        proj_id = project_id or os.environ.get('GCP_PROJECT_ID')

        if not proj_id:
            raise Exception("GCP_PROJECT_ID not found")

        project_path = f"projects/{proj_id}"

        topics = []
        for topic in publisher.list_topics(request={"project": project_path}):
            topics.append({
                'name': topic.name.split('/')[-1],
                'full_name': topic.name,
                'labels': dict(topic.labels) if topic.labels else {}
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(topics),
            'topics': topics
        }
    except Exception as e:
        logger.error(f"Error listing Pub/Sub topics: {str(e)}")
        return {'success': False, 'error': str(e)}


def publish_pubsub_message(
    topic_name: str,
    message_data: str,
    project_id: Optional[str] = None,
    attributes: Optional[Dict[str, str]] = None
) -> Dict[str, Any]:
    """
    Publish a message to a Pub/Sub topic.

    Args:
        topic_name: Topic name
        message_data: Message data to publish
        project_id: GCP project ID
        attributes: Optional message attributes

    Returns:
        Dictionary with publish result
    """
    try:
        from google.cloud import pubsub_v1

        publisher = pubsub_v1.PublisherClient()
        proj_id = project_id or os.environ.get('GCP_PROJECT_ID')

        if not proj_id:
            raise Exception("GCP_PROJECT_ID not found")

        topic_path = publisher.topic_path(proj_id, topic_name)

        # Encode message data
        data = message_data.encode('utf-8')

        # Publish message
        if attributes:
            future = publisher.publish(topic_path, data, **attributes)
        else:
            future = publisher.publish(topic_path, data)

        message_id = future.result()

        return {
            'success': True,
            'project': proj_id,
            'topic': topic_name,
            'message_id': message_id,
            'message': f'Message published to topic {topic_name} with ID: {message_id}'
        }
    except Exception as e:
        logger.error(f"Error publishing Pub/Sub message: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_bigquery_datasets(project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List BigQuery datasets.

    Args:
        project_id: GCP project ID

    Returns:
        Dictionary with BigQuery datasets information
    """
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=project_id or os.environ.get('GCP_PROJECT_ID'))

        datasets = []
        for dataset in client.list_datasets():
            datasets.append({
                'dataset_id': dataset.dataset_id,
                'full_id': dataset.full_dataset_id,
                'project': dataset.project,
                'location': dataset.location if hasattr(dataset, 'location') else None,
                'labels': dict(dataset.labels) if hasattr(dataset, 'labels') and dataset.labels else {}
            })

        return {
            'success': True,
            'project': client.project,
            'count': len(datasets),
            'datasets': datasets
        }
    except Exception as e:
        logger.error(f"Error listing BigQuery datasets: {str(e)}")
        return {'success': False, 'error': str(e)}


def query_bigquery(
    query: str,
    project_id: Optional[str] = None,
    max_results: int = 100
) -> Dict[str, Any]:
    """
    Execute a BigQuery SQL query.

    Args:
        query: SQL query to execute
        project_id: GCP project ID
        max_results: Maximum number of results to return

    Returns:
        Dictionary with query results
    """
    try:
        from google.cloud import bigquery

        client = bigquery.Client(project=project_id or os.environ.get('GCP_PROJECT_ID'))

        query_job = client.query(query)
        results = query_job.result(max_results=max_results)

        # Convert results to list of dicts
        rows = []
        for row in results:
            rows.append(dict(row))

        return {
            'success': True,
            'project': client.project,
            'total_rows': results.total_rows,
            'rows_returned': len(rows),
            'rows': rows,
            'query': query
        }
    except Exception as e:
        logger.error(f"Error executing BigQuery query: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_secrets(project_id: Optional[str] = None) -> Dict[str, Any]:
    """
    List Secret Manager secrets.

    Args:
        project_id: GCP project ID

    Returns:
        Dictionary with secrets information
    """
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        proj_id = project_id or os.environ.get('GCP_PROJECT_ID')

        if not proj_id:
            raise Exception("GCP_PROJECT_ID not found")

        parent = f"projects/{proj_id}"

        secrets = []
        for secret in client.list_secrets(request={"parent": parent}):
            secrets.append({
                'name': secret.name.split('/')[-1],
                'full_name': secret.name,
                'labels': dict(secret.labels) if secret.labels else {},
                'create_time': secret.create_time.isoformat() if secret.create_time else None
            })

        return {
            'success': True,
            'project': proj_id,
            'count': len(secrets),
            'secrets': secrets
        }
    except Exception as e:
        logger.error(f"Error listing Secret Manager secrets: {str(e)}")
        return {'success': False, 'error': str(e)}


def get_secret_value(
    secret_name: str,
    version: str = 'latest',
    project_id: Optional[str] = None
) -> Dict[str, Any]:
    """
    Get the value of a secret from Secret Manager.

    Args:
        secret_name: Secret name
        version: Secret version (default: 'latest')
        project_id: GCP project ID

    Returns:
        Dictionary with secret value
    """
    try:
        from google.cloud import secretmanager

        client = secretmanager.SecretManagerServiceClient()
        proj_id = project_id or os.environ.get('GCP_PROJECT_ID')

        if not proj_id:
            raise Exception("GCP_PROJECT_ID not found")

        name = f"projects/{proj_id}/secrets/{secret_name}/versions/{version}"
        response = client.access_secret_version(request={"name": name})

        payload = response.payload.data.decode('UTF-8')

        return {
            'success': True,
            'project': proj_id,
            'secret_name': secret_name,
            'version': version,
            'value': payload
        }
    except Exception as e:
        logger.error(f"Error getting secret value: {str(e)}")
        return {'success': False, 'error': str(e)}


def list_cloud_logs(
    project_id: Optional[str] = None,
    filter_query: Optional[str] = None,
    max_entries: int = 50
) -> Dict[str, Any]:
    """
    List Cloud Logging entries.

    Args:
        project_id: GCP project ID
        filter_query: Optional filter query (e.g., 'severity>=ERROR')
        max_entries: Maximum number of log entries to return

    Returns:
        Dictionary with log entries
    """
    try:
        from google.cloud import logging

        client = logging.Client(project=project_id or os.environ.get('GCP_PROJECT_ID'))

        if filter_query:
            iterator = client.list_entries(filter_=filter_query, max_results=max_entries)
        else:
            iterator = client.list_entries(max_results=max_entries)

        entries = []
        for entry in iterator:
            entries.append({
                'timestamp': entry.timestamp.isoformat() if entry.timestamp else None,
                'severity': entry.severity,
                'log_name': entry.log_name,
                'resource_type': entry.resource.type if entry.resource else None,
                'payload': str(entry.payload),
                'labels': dict(entry.labels) if entry.labels else {}
            })

        return {
            'success': True,
            'project': client.project,
            'count': len(entries),
            'filter': filter_query,
            'entries': entries
        }
    except Exception as e:
        logger.error(f"Error listing Cloud Logging entries: {str(e)}")
        return {'success': False, 'error': str(e)}


# ==================== TOOL REGISTRATION ====================


def get_tools() -> List[Dict[str, Any]]:
    """
    Get list of GCP tool definitions for the agent.

    Returns:
        List of tool definitions with name, description, input_schema, and handler
    """
    return [
        # Compute Engine Operations
        {
            'name': 'list_compute_instances',
            'description': 'List Google Compute Engine instances',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'zone': {'type': 'string', 'description': 'Zone to filter instances (optional)'}
                }
            },
            'handler': list_compute_instances
        },
        {
            'name': 'manage_compute_instance',
            'description': 'Manage GCE instance (start, stop, reset)',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_name': {'type': 'string', 'description': 'Instance name'},
                    'zone': {'type': 'string', 'description': 'Zone where instance is located'},
                    'action': {'type': 'string', 'description': 'Action: start, stop, or reset', 'enum': ['start', 'stop', 'reset']},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['instance_name', 'zone', 'action']
            },
            'handler': manage_compute_instance
        },
        {
            'name': 'create_compute_instance',
            'description': 'Create a new Google Compute Engine instance',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_name': {'type': 'string', 'description': 'Name for the instance'},
                    'zone': {'type': 'string', 'description': 'Zone (e.g., us-central1-a, us-west1-b, europe-west1-b)'},
                    'machine_type': {'type': 'string', 'description': 'Machine type (e.g., e2-medium, n1-standard-1, n2-standard-2)', 'default': 'e2-medium'},
                    'image_project': {'type': 'string', 'description': 'Image project (default: debian-cloud)', 'default': 'debian-cloud'},
                    'image_family': {'type': 'string', 'description': 'Image family (default: debian-11)', 'default': 'debian-11'},
                    'disk_size_gb': {'type': 'integer', 'description': 'Boot disk size in GB (default: 10)', 'default': 10},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['instance_name', 'zone']
            },
            'handler': create_compute_instance
        },
        {
            'name': 'delete_compute_instance',
            'description': 'Delete a Google Compute Engine instance',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_name': {'type': 'string', 'description': 'Instance name'},
                    'zone': {'type': 'string', 'description': 'Zone where instance is located'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['instance_name', 'zone']
            },
            'handler': delete_compute_instance
        },
        # Cloud Storage Operations
        {
            'name': 'list_storage_buckets',
            'description': 'List Google Cloud Storage buckets',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_storage_buckets
        },
        {
            'name': 'create_storage_bucket',
            'description': 'Create a new Google Cloud Storage bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name (must be globally unique)'},
                    'location': {'type': 'string', 'description': 'Location (e.g., US, EU, us-central1)', 'default': 'US'},
                    'storage_class': {'type': 'string', 'description': 'Storage class: STANDARD, NEARLINE, COLDLINE, ARCHIVE', 'default': 'STANDARD'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['bucket_name']
            },
            'handler': create_storage_bucket
        },
        {
            'name': 'delete_storage_bucket',
            'description': 'Delete a Google Cloud Storage bucket',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'bucket_name': {'type': 'string', 'description': 'Bucket name'},
                    'force': {'type': 'boolean', 'description': 'If true, delete all objects first', 'default': False},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['bucket_name']
            },
            'handler': delete_storage_bucket
        },
        # GKE Operations
        {
            'name': 'list_gke_clusters',
            'description': 'List Google Kubernetes Engine (GKE) clusters',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'location': {'type': 'string', 'description': 'Location to filter clusters (optional)'}
                }
            },
            'handler': list_gke_clusters
        },
        # Cloud SQL Operations
        {
            'name': 'list_cloud_sql_instances',
            'description': 'List Google Cloud SQL instances',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_cloud_sql_instances
        },
        {
            'name': 'create_cloud_sql_instance',
            'description': 'Create a new Google Cloud SQL instance',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'instance_name': {'type': 'string', 'description': 'Instance name'},
                    'database_version': {'type': 'string', 'description': 'Database version: MYSQL_8_0, POSTGRES_14, SQLSERVER_2019_STANDARD', 'default': 'MYSQL_8_0'},
                    'tier': {'type': 'string', 'description': 'Machine tier (db-f1-micro, db-n1-standard-1, db-n1-standard-2)', 'default': 'db-f1-micro'},
                    'region': {'type': 'string', 'description': 'Region (e.g., us-central1, us-east1, europe-west1)', 'default': 'us-central1'},
                    'root_password': {'type': 'string', 'description': 'Root user password (optional, auto-generated if not provided)'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['instance_name']
            },
            'handler': create_cloud_sql_instance
        },
        # Cloud Monitoring
        {
            'name': 'get_gcp_metrics',
            'description': 'Get Google Cloud Monitoring metrics',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'metric_type': {'type': 'string', 'description': 'Metric type (e.g., compute.googleapis.com/instance/cpu/utilization)'},
                    'resource_type': {'type': 'string', 'description': 'Resource type (e.g., gce_instance)'},
                    'hours': {'type': 'integer', 'description': 'Hours to look back (default: 1)', 'default': 1},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['metric_type', 'resource_type']
            },
            'handler': get_gcp_metrics
        },
        # Cloud Functions
        {
            'name': 'list_cloud_functions',
            'description': 'List Google Cloud Functions',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'location': {'type': 'string', 'description': 'Location to filter functions (optional)'}
                }
            },
            'handler': list_cloud_functions
        },
        # Cloud Run
        {
            'name': 'list_cloud_run_services',
            'description': 'List Google Cloud Run services',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'region': {'type': 'string', 'description': 'GCP region (default: us-central1)', 'default': 'us-central1'}
                }
            },
            'handler': list_cloud_run_services
        },
        # Pub/Sub
        {
            'name': 'list_pubsub_topics',
            'description': 'List Google Cloud Pub/Sub topics',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_pubsub_topics
        },
        {
            'name': 'publish_pubsub_message',
            'description': 'Publish a message to a Pub/Sub topic',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'topic_name': {'type': 'string', 'description': 'Topic name'},
                    'message_data': {'type': 'string', 'description': 'Message data to publish'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'attributes': {'type': 'object', 'description': 'Optional message attributes (key-value pairs)'}
                },
                'required': ['topic_name', 'message_data']
            },
            'handler': publish_pubsub_message
        },
        # BigQuery
        {
            'name': 'list_bigquery_datasets',
            'description': 'List BigQuery datasets',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_bigquery_datasets
        },
        {
            'name': 'query_bigquery',
            'description': 'Execute a BigQuery SQL query',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'query': {'type': 'string', 'description': 'SQL query to execute'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'max_results': {'type': 'integer', 'description': 'Maximum number of results to return (default: 100)', 'default': 100}
                },
                'required': ['query']
            },
            'handler': query_bigquery
        },
        # Secret Manager
        {
            'name': 'list_secrets',
            'description': 'List Google Cloud Secret Manager secrets',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                }
            },
            'handler': list_secrets
        },
        {
            'name': 'get_secret_value',
            'description': 'Get the value of a secret from Secret Manager',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'secret_name': {'type': 'string', 'description': 'Secret name'},
                    'version': {'type': 'string', 'description': 'Secret version (default: latest)', 'default': 'latest'},
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'}
                },
                'required': ['secret_name']
            },
            'handler': get_secret_value
        },
        # Cloud Logging
        {
            'name': 'list_cloud_logs',
            'description': 'List Google Cloud Logging entries',
            'input_schema': {
                'type': 'object',
                'properties': {
                    'project_id': {'type': 'string', 'description': 'GCP project ID (optional)'},
                    'filter_query': {'type': 'string', 'description': 'Optional filter query (e.g., severity>=ERROR)'},
                    'max_entries': {'type': 'integer', 'description': 'Maximum number of log entries (default: 50)', 'default': 50}
                }
            },
            'handler': list_cloud_logs
        }
    ]
