# GEE_Backend
A Flask-based backend service for integrating Google Earth Engine (GEE) with Firebase data storage, designed for managing geospatial vegetation data and plant observations.

## Features
- Earth Engine Integration: Authenticates with GEE using service account credentials
- Firebase Firestore: Stores plant observation data with nested collections
- Image Processing: Retrieves and renders satellite imagery from GEE collections
- Crown Tracking: Manages tree crown polygons with date-based filtering and styling

## Setup
```
git clone https://github.com/your-username/GEE_Backend.git
cd GEE_Backend
pip install -r requirements.txt
```

## Configuration
Create .env file with these variables:
```commandline
GEE_SERVICE_ACCOUNT_JSON="path/to/service-account.json"
GEE_SERVICE_ACCOUNT="your-service-account@project.iam.gserviceaccount.com"
GEE_PROJECT_ID="your-gee-project-id"
FIREBASE_CREDENTIALS="path/to/firebase-credentials.json"
CORS_ORIGINS="http://localhost:5173"
IMAGE_COLLECTION="EE_IMAGE_COLLECTION_PATH"
CROWNS="EE_CROWNS_COLLECTION_PATH"
LABELS="EE_LABELS_COLLECTION_PATH"
```

## API Endpoints
### Image Endpoints
```
GET /image?date=YYYY-MM-DD - Returns metadata for first image matching date
GET /render-image?date=YYYY-MM-DD&max_size=3930 - Redirects to rendered image thumbnail
```

### Crown Endpoints
```
GET /crowns?date=YYYY-MM-DD - Returns styled crown features with existing database matches
GET /get-globalids-by-date?date=YYYY-MM-DD - Lists GlobalIDs with existing observations
```
### Observation Endpoints
```
POST /observations - Stores plant observation data with nested documents.
{
  "globalId": "string",
  "latinName": "string",
  "date": "string",
  "leafing": "string",
  "isFlowering": boolean,
  "floweringIntensity": number,
  "segmentation": "string"
}
```
