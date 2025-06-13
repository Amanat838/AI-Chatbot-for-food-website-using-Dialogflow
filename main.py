from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import db_hepler  # Make sure this module and the get_order_status function work properly
import traceback
import generic_helper


app = FastAPI()

inprogress_orders = {}


@app.post("/")
async def handle_request(request: Request):
    # Retrieve the JSON data from the request
    payload = await request.json()

    # Extract the necessary information from the payload
    # based on the structure of the WebhookRequest from Dialogflow
    intent = payload['queryResult']['intent']['displayName']
    parameters = payload['queryResult']['parameters']
    output_contexts = payload['queryResult']['outputContexts']
    session_id = generic_helper.extract_session_id(output_contexts[0]['name'])

    intent_handler_dict = {
        'order.add - context: ongoing-order': add_to_order,
        'order.remove - context: ongoing-order': remove_from_order,
        'order.complete - context: ongoing-order': complete_order,
        'track.order - context: ongoing-tracking': track_order
    }

    return intent_handler_dict[intent](parameters, session_id)


def track_order(parameters: dict, session_id: str):
    try:
        print("📦 Parameters received:", parameters)

        raw_id = parameters.get('number')
        print("🔢 Raw ID from Dialogflow:", raw_id)

        # Format order ID
        order_id = str(int(float(raw_id)))
        print("🎯 Formatted order ID:", order_id)

        # Fetch status from DB
        order_status = db_hepler.get_order_status(order_id)
        print("📋 Order status from DB:", order_status)

    except Exception as e:
        print("❌ Error fetching order status:", str(e))
        traceback.print_exc()
        return JSONResponse(content={"fulfillmentText": "Could not fetch order status. Please try again later."})

    # Build response
    if order_status:
        fulfillment_text = f"✅ Order ID {order_id} is currently {order_status}."
    else:
        fulfillment_text = f"❌ Order ID {order_id} not found."

    return JSONResponse(content={"fulfillmentText": fulfillment_text})


def add_to_order(parameters: dict, session_id: str):
    food_items = parameters["food-item"]
    quantities = parameters["number"]

    if len(food_items) != len(quantities):
        fulfillment_text = "Sorry I didn't understand. Can you please specify food items and quantities clearly?"

    else:
        new_food_dict = dict(zip(food_items, quantities))

        if session_id in inprogress_orders:
            current_food_dict = inprogress_orders[session_id]
            current_food_dict.update(new_food_dict)
            inprogress_orders[session_id] = current_food_dict
        else:
            inprogress_orders[session_id] = new_food_dict

        order_str = generic_helper.get_str_from_food_dict(
            inprogress_orders[session_id])

        fulfillment_text = f"So far you have {order_str}, do you want anything else?"

    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
    })


def complete_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        fulfillment_text = "We are having trouble placing your order, try to order again"
    else:
        order = inprogress_orders[session_id]
        order_id = save_to_db(order)

        if order_id == -1:
            fulfillment_text = "We are having trouble placing your order, try to order again"
        else:
            order_total = db_hepler.get_total_order_price(order_id)
            fulfillment_text = f"Your order has been placed successfully with order ID {order_id} and order total {order_total}. Thank you for ordering!"

        del inprogress_orders[session_id]

    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
    })


def save_to_db(order: dict):
    next_order_id = db_hepler.get_next_order_id()
    for food_item, quantity in order.items():
        r_code = db_hepler.insert_order_item(
            food_item, quantity, next_order_id)

    if r_code == -1:
        return -1

    db_hepler.insert_order_tracking(next_order_id, "in progress")

    return next_order_id


def remove_from_order(parameters: dict, session_id: str):
    if session_id not in inprogress_orders:
        fulfillment_text = "We are having trouble removing items from your order, try to order again"

    current_order = inprogress_orders[session_id]
    food_items = parameters['food-item']

    removed_items = []
    no_such_items = []
    for item in food_items:
        if item not in current_order:
            no_such_items.append(item)
        else:
            removed_items.append(item)
            del current_order[item]
    if len(removed_items) > 0:
        fulfillment_text = f"Removed {', '.join(removed_items)} from your order."

    if len(no_such_items) > 0:
        fulfillment_text += f" However, {', '.join(no_such_items)} were not in your order."

    if len(current_order.keys()) == 0:
        fulfillment_text += " Your order is now empty. You can add more items if you want."

    else:
        order_str = generic_helper.get_str_from_food_dict(current_order)
        fulfillment_text += f" Your current order is: {order_str}."
    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
    })
