from flask import Flask, jsonify, request, redirect, send_file
from flask_cors import CORS
import ee
from dotenv import load_dotenv
import threading
import firebase_admin
from firebase_admin import credentials, firestore
import os
from secret_handler import load_secrets

load_secrets()

if not os.environ.get('GAE_ENV', '').startswith('standard'):
    load_dotenv()

GEE_SERVICE_ACCOUNT_JSON = os.getenv('GEE_SERVICE_ACCOUNT_JSON')
GEE_SERVICE_ACCOUNT = os.getenv('GEE_SERVICE_ACCOUNT')
GEE_PROJECT_ID = os.getenv('GEE_PROJECT_ID')
CORS_ORIGINS = os.getenv('CORS_ORIGINS')

FIREBASE_CREDENTIALS = os.getenv('FIREBASE_CREDENTIALS')

IMAGE_COLLECTION = os.getenv('IMAGE_COLLECTION')
CROWNS = os.getenv('CROWNS')
LABELS = os.getenv('LABELS')

app = Flask(__name__)
CORS(app, resources={
    r"/api/*": {"origins": CORS_ORIGINS,
                "method": ["GET", "POST"],
                "allow_headers": ["Content-Type", "Authorization"],
                "supports_credentials": True}
})

cred = credentials.Certificate(os.getenv('FIREBASE_CREDENTIALS'))
firebase_admin.initialize_app(cred)
db = firestore.client()


def authenticate_ee():
    try:
        service_account = GEE_SERVICE_ACCOUNT
        credentials = ee.ServiceAccountCredentials(service_account, GEE_SERVICE_ACCOUNT_JSON)
        ee.Initialize(credentials, project=GEE_PROJECT_ID)
    except:
        ee.Initialize(project=GEE_PROJECT_ID)


threading.Thread(target=authenticate_ee).start()


@app.before_request
def before_first_request():
    authenticate_ee()


@app.before_request
def load_ee_assets():
    global collection, crowns, labels
    collection = ee.ImageCollection(IMAGE_COLLECTION)
    crowns = ee.FeatureCollection(CROWNS)
    labels = ee.FeatureCollection(LABELS)


@app.after_request
def add_cors_headers(response):
    allowed_origins = os.getenv('CORS_ORIGINS', '').split(',')
    origin = request.headers.get('Origin', '')

    if origin in allowed_origins:
        response.headers['Access-Control-Allow-Origin'] = origin
    response.headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS'
    response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
    response.headers['Access-Control-Allow-Credentials'] = 'true'
    return response


@app.route('/image', methods=['GET'])
def get_image():
    date = request.args.get('date')
    image = collection.filter(ee.Filter.eq('system:time_start', ee.Date(date).millis())).first()
    return jsonify(image.getInfo())


@app.route('/render-image', methods=['GET'])
def render_image():
    date = request.args.get('date')
    max_size = int(request.args.get('max_size', 3930))

    image = collection.filter(ee.Filter.eq('system:time_start', ee.Date(date).millis())).first()

    # Scale image instead of using reduceResolution
    image_url = image.getThumbURL({
        'bands': ['b1', 'b2', 'b3'],
        'min': 0,
        'max': 255,
        'dimensions': max_size,
    })
    return redirect(image_url)


@app.route('/crowns', methods=['GET'])
def get_crowns():
    try:
        date = request.args.get('date')
        if not date:
            return jsonify({"error": "Date parameter is required"}), 400

        existing_ids = get_existing_global_ids(date)

        ee_existing_ids = ee.List(existing_ids)

        merged_crowns = merge_crowns_with_labels(crowns, labels)

        filtered_crowns = get_crowns_by_date(merged_crowns, date)

        if filtered_crowns.size().getInfo() == 0:
            return jsonify({"message": "No crowns found for this date"}), 404

        existing_features = filtered_crowns.filter(ee.Filter.inList('GlobalID', ee_existing_ids))
        missing_features = filtered_crowns.filter(ee.Filter.inList('GlobalID', ee_existing_ids).Not())

        styled_existing = existing_features.map(lambda f:
                                                f.set('style', ee.Dictionary({
                                                    'color': '#0000FF',  # Red for features in database
                                                    'width': 2,
                                                    'fillColor': '00000000'
                                                }))
                                                )

        styled_missing = missing_features.map(lambda f:
                                              f.set('style', ee.Dictionary({
                                                  'color': '#FF0000',  # Blue for features not in database
                                                  'width': 1,
                                                  'fillColor': '00000000'
                                              }))
                                              )

        # Merge the collections back together
        styled_crowns = styled_existing.merge(styled_missing)

        result = styled_crowns.getInfo()
        return jsonify(result), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500


def get_existing_global_ids(date):
    """Helper function to fetch existing IDs"""
    plants_ref = db.collection('plants')
    formatted_date = date.replace('-', '_')
    query = plants_ref.where('date', '==', formatted_date)

    # Add debug logging
    results = [str(doc.to_dict().get('globalId')).strip() for doc in query.stream()
               if doc.to_dict().get('globalId')]

    return results


def _build_preflight_response():
    response = jsonify()
    response.headers.add("Access-Control-Allow-Origin", ", ".join(os.getenv('CORS_ORIGINS', '').split(',')))
    response.headers.add("Access-Control-Allow-Headers", "Content-Type, Authorization")
    response.headers.add("Access-Control-Allow-Methods", "POST, OPTIONS")
    return response


@app.route('/observations', methods=['POST', 'OPTIONS'])
def add_observation():
    if request.method == 'OPTIONS':
        return _build_preflight_response()
    try:
        data = request.json
        composite_id = f"{data['globalId']}_{data['date'].replace('_', '-')}"
        plant_ref = db.collection('plants').document(composite_id)

        # Update parent document
        plant_ref.set({
            'globalId': data['globalId'],
            'latinName': data['latinName'],
            'date': data['date']
        }, merge=True)

        # Create new observation document with auto-generated ID
        obs_ref = plant_ref.collection('observations').document()
        obs_ref.set({
            'leafing': data['leafing'],
            'isFlowering': data['isFlowering'],
            'floweringIntensity': data['floweringIntensity'],
            'segmentation': data['segmentation']
        })

        return jsonify({
            "success": True,
            "parent_id": composite_id,
            "observation_id": obs_ref.id
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route('/get-globalids-by-date', methods=['GET'])
def get_globalids_by_date():
    try:
        date = request.args.get('date')

        plants_ref = db.collection('plants')
        query = plants_ref.where('date', '==', date)
        docs = query.stream()

        global_ids = [doc.to_dict().get('globalId') for doc in docs if doc.to_dict().get('globalId')]

        return jsonify({
            "date": date,
            "global_ids": global_ids,
            "count": len(global_ids)
        }), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 400


def merge_crowns_with_labels(crowns, labels):
    join = ee.Join.saveAll(matchesKey='matches', outer=True)
    filter = ee.Filter.And(
        ee.Filter.equals(leftField='GlobalID', rightField='GlobalID'),
        ee.Filter.equals(leftField='date', rightField='date')
    )
    joined = join.apply(crowns, labels, filter)

    def add_leafing_final(feat):
        matches = ee.List(feat.get('matches'))
        leafing_final = ee.Algorithms.If(
            matches.size().gt(0),
            ee.Feature(matches.get(0)).get('leafing_label'),
            "none"
        )
        return feat.set('leafing', leafing_final)

    return joined.map(add_leafing_final)


def get_crowns_by_date(crowns, date):
    return crowns.filter(ee.Filter.eq('date', date.replace('-', '_')))


def style_by_property(collection, property):
    return collection.map(lambda feature: feature.set('style', {
        'color': ee.Algorithms.If(ee.Algorithms.IsEqual(feature.get(property), 'none'), '#FF0000',
                                  ee.Algorithms.If(ee.Algorithms.IsEqual(feature.get(property), 'Partially Leafed'),
                                                   '#00FF00',
                                                   ee.Algorithms.If(
                                                       ee.Algorithms.IsEqual(feature.get(property), 'Out of Leafs'),
                                                       '#0000FF',
                                                       ee.Algorithms.If(
                                                           ee.Algorithms.IsEqual(feature.get(property), 'Fully Leafed'),
                                                           '#FFFF00',
                                                           '#FFFFFF')))),
        'width': 1,
        'fillColor': '00000000'
    }))


if __name__ == '__main__':
    app.run()
