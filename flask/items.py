from fastapi import APIRouter


router = APIRouter()


@router.get("/api/data")
async def get_sample_data():
    return {
        "data": [
            {"id": 1, "name": "Sample Item 1", "value": 100},
            {"id": 2, "name": "Sample Item 2", "value": 200},
            {"id": 3, "name": "Sample Item 3", "value": 300},
        ],
        "total": 3,
        "timestamp": "2024-01-01T00:00:00Z",
    }


@router.get("/api/items/{item_id}")
async def get_item(item_id: int):
    return {
        "item": {
            "id": item_id,
            "name": f"Sample Item {item_id}",
            "value": item_id * 100,
        },
        "timestamp": "2024-01-01T00:00:00Z",
    }
