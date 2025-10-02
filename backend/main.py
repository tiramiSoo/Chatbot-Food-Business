from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
import db_helper
import generic_helper
import pathlib
app = FastAPI()

in_progress_orders = {}
status = {}

# Path to your home.html file
FRONTEND_DIR = pathlib.Path(r"D:\CongViec\Chatbot-Food-Business\frontend")
# 👉 Serve static files (CSS, JS, images) at /static
app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")

# 👉 Serve home.html at root
@app.get("/", response_class=HTMLResponse)
async def serve_home():
    with open(FRONTEND_DIR / "home.html", "r", encoding="utf-8") as f:
        return f.read()
@app.post("/")
async def handle_request(request: Request):
    payload = await request.json()

    # Extract intent and parameters
    intent = payload['queryResult']['intent']['displayName']
    parameters = payload['queryResult']['parameters']
    output_contexts = payload['queryResult']['outputContexts']
    session_id = generic_helper.extract_session_id(output_contexts[0]['name'])
    user_msg = payload["queryResult"]["queryText"]
    intent_handler_dict = {
        'new.order': clear_in_progress,
        'order.add - context: ongoing-order': add_to_order,
        'order.remove - context: ongoing-order': remove_from_order,
        'order.complete - context: ongoing-order': complete_order,
        'track.order - context: ongoing-tracking': track_order
    }

    return intent_handler_dict[intent](parameters, session_id, user_msg)


# def submit_review(parameters, session_id, user_msg):
    db_helper.insert_review(status[session_id], user_msg)

def clear_in_progress(parameters: dict, session_id: str, user_msg):
    msg = user_msg.strip().lower()

    # Keywords that mean start a fresh order
    reset_keywords = ["new order", "reset order", "start over", "clear order"]

    # 1️⃣ Check reset first, no matter what parameters came in
    if any(keyword in msg for keyword in reset_keywords):
        if session_id in in_progress_orders:
            del in_progress_orders[session_id]  # clear old order completely
        # fulfillment_text = "Okay, I’ve cleared your previous order. Please tell me what you’d like to order."
        # print("Order cleared for session:", session_id)
        # return JSONResponse(content={'fulfillmentText': fulfillment_text})

def remove_from_order(parameters: dict , session_id: str, user_msg):
    if session_id not in in_progress_orders:
        return JSONResponse(content={
            "fulfillmentText": "I'm having a trouble finding your order. Sorry! Can you place a new order please?"
        })

    current_order = in_progress_orders[session_id]
    food_items = parameters['food-item']
    quantities = parameters['number']

    removed_items = []
    no_such_items = []

    # If quantities are missing or empty, remove the whole item
    if not quantities or len(quantities) == 0:
        for item in food_items:
            if item in current_order:
                removed_items.append(item)
                del current_order[item]
            else:
                no_such_items.append(item)
    else:
        # Quantities present; match lengths and decrement appropriately
        if len(food_items) != len(quantities):
            return JSONResponse(content={
                "fulfillmentText": "Sorry, quantities and items don't match for removal. Please try again."
            })

        for item, qty_to_remove in zip(food_items, quantities):
            if item not in current_order:
                no_such_items.append(item)
            else:
                current_qty = current_order[item]
                new_qty = current_qty - qty_to_remove

                if new_qty > 0:
                    current_order[item] = new_qty
                    removed_items.append(f"{qty_to_remove} {item}")
                else:
                    removed_items.append(f"{current_qty} {item}")
                    del current_order[item]

    fulfillment_text = ""

    if removed_items:
        fulfillment_text += f"Removed {', '.join(removed_items)} from your order."

    if no_such_items:
        fulfillment_text += f" Your current order does not have {', '.join(no_such_items)}."

    if len(current_order) == 0:
        fulfillment_text += " Your order is empty!"
    else:
        order_str = generic_helper.get_str_from_food_dict(current_order)
        fulfillment_text += f" Here is what is left in your order: {order_str}"

    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
    })

def add_to_order(parameters: dict, session_id: str, user_msg):
    food_items = parameters['food-item']
    quantities = parameters['number']

    if len(food_items) != len(quantities):
        fulfillment_text = "Sorry I didn't understand. Can you please specify food items and quantities?"
    else:
        new_food_dict = dict(zip(food_items, quantities))
        if session_id in in_progress_orders:
            current_food_dict = in_progress_orders[session_id]
            current_food_dict.update(new_food_dict)
            in_progress_orders[session_id] = current_food_dict
        else:
            in_progress_orders[session_id] = new_food_dict

        # print("**********")
        # print(in_progress_orders)

        order_str = generic_helper.get_str_from_food_dict(in_progress_orders[session_id])
        fulfillment_text = f"So far you have: {order_str}. Do you need anything else?"

    return JSONResponse(content=
        {'fulfillmentText': fulfillment_text})

def track_order(parameters: dict, session_id: str, user_msg):
    order_id = int(parameters['order_id'])
    output_contexts = []
    order_status = db_helper.get_order_status(order_id)

    if order_status:
        if order_status == "delivered":
            fulfillment_text = f"Your order is {order_status}. Thanks for your order!"
        else:
            fulfillment_text = f"The order status for order id: {order_id} is: {order_status}. Please wait a moment."
    else:
        fulfillment_text = f"No order found with order id: {order_id}"

    return JSONResponse(content={
        "fulfillmentText": fulfillment_text
    })

def complete_order(parameters: dict, session_id: str, user_msg):
    if session_id not in in_progress_orders:
        fulfillment_text = "I'm having a trouble finding your order. Sorry! Can you place a new order?"
        return JSONResponse(content={
            "fulfillmentText": fulfillment_text
        })
    else:
        order = in_progress_orders[session_id]
        order_id = save_to_db(order)

        if order_id == -1:
            fulfillment_text = "Sorry, I couldn't process your order due to a backend error. " \
                               "Please place a new order again"
        else:
            order_total = db_helper.get_total_order_price(order_id)
            fulfillment_text = f"Awesome. We have placed your order. " \
                               f"Here is your order id # {order_id}. " \
                               f"Your order total is {order_total} which you can pay at the time of delivery!"

        del in_progress_orders[session_id]

        return JSONResponse(content={
            "fulfillmentText": fulfillment_text
        })

def save_to_db(order: dict):
    next_order_id = db_helper.get_next_order_id()

    for food_item, quantity in order.items():
        rcode = db_helper.insert_order_item(
            food_item,
            quantity,
            next_order_id
        )

        if rcode == -1:
            return -1

    db_helper.insert_order_tracking(next_order_id, "in progress")

    return next_order_id
