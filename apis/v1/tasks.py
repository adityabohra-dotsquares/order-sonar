import os
from loguru import logger
from celery_app import app
from service.import_export_service import ImportExportService

@app.task(name="import_product_zone_rates_task")
def import_product_zone_rates_task(file_url: str, dry_run: bool, task_id: str):
    """
    Celery task that downloads the file from GCS and runs the async import.
    """
    logger.info(f"Starting Celery task for GCS URL: {file_url}")
    temp_path = None
    try:
        from utils.gcp_bucket import download_from_gcs
        
        # Download file to local temporary storage
        temp_path = download_from_gcs(file_url)
        logger.info(f"Downloaded file to temp path: {temp_path}")

        if not os.path.exists(temp_path):
            logger.error(f"File download failed or not found: {temp_path}")
            return

        with open(temp_path, "rb") as f:
            file_content = f.read()

        # Extract filename from URL for logging
        filename = file_url.split("/")[-1]
        
        # Run async function using asyncio
        import asyncio
        
        try:
            # Wrap in single async function to dispose before event loop closes
            async def run_task_and_dispose():
                try:
                    from database import async_session
                    # Instantiate service with a fresh session
                    async with async_session() as db:
                        service = ImportExportService(db)
                        await service.process_background_import_product_zone_rates(file_content, filename, dry_run, task_id)
                finally:
                    try:
                        from database import engine
                        await engine.dispose()
                        logger.info("SQLAlchemy Engine pool disposed inside loop.")
                    except Exception as dispose_error:
                        logger.error(f"Failed to dispose engine inside loop: {dispose_error}")

            asyncio.run(run_task_and_dispose())
            logger.info(f"Async import completed for {filename}")
        except Exception as e:
            logger.error(f"Error running async import for {filename}: {e}")

    except Exception as e:
        logger.error(f"Celery task wrapper error: {e}")
    finally:
        # Cleanup file after processing
        try:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)
                logger.info(f"Cleaned up temp import file: {temp_path}")
        except Exception as e:
            logger.error(f"Error removing file {temp_path}: {e}")

@app.task(name="sync_tracking_updates_task")
def sync_tracking_updates_task():
    """
    Placeholder task for periodic execution (e.g., syncing tracking updates).
    """
    logger.info("Starting periodic tracking sync task")
    # Add your sync logic here
    # Example: call AramexService or ShipStationService
    return "Sync complete"
