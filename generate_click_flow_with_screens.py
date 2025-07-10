import os
import json
import requests
import argparse
from collections import defaultdict

def fetch_figma_file(token, file_key):
    headers = {'X-Figma-Token': token}
    url = f'https://api.figma.com/v1/files/{file_key}'
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json()

def build_node_maps(node, name_map, parent_map, node_lookup, parent=None):
    node_id = node.get("id")
    if node_id:
        name_map[node_id] = node.get("name", "Unnamed")
        parent_id = parent.get("id") if parent else None
        parent_map[node_id] = parent_id
        node_lookup[node_id] = node
    for child in node.get("children", []):
        build_node_maps(child, name_map, parent_map, node_lookup, node)

def find_frame_ancestor(node, parent_map, node_lookup):
    current = node
    while current:
        if current.get("type") == "FRAME" and 'absoluteBoundingBox' in current:
            return current
        current_id = current.get("id")
        parent_id = parent_map.get(current_id)
        current = node_lookup.get(parent_id) if parent_id else None
    return None

def extract_clickables(node, parent_map, node_lookup, clickables):
    for child in node.get("children", []):
        extract_clickables(child, parent_map, node_lookup, clickables)

    has_link = 'prototypeInteractions' in node or 'transitionNodeID' in node
    if not has_link or 'absoluteBoundingBox' not in node:
        return

    box = node['absoluteBoundingBox']
    mid_x = box['x'] + box['width'] / 2
    mid_y = box['y'] + box['height'] / 2

    frame = find_frame_ancestor(node, parent_map, node_lookup)
    from_screen = frame.get("name", "Unknown") if frame else "Unknown"

    if frame and 'absoluteBoundingBox' in frame:
        frame_box = frame['absoluteBoundingBox']
        tap_x = mid_x - frame_box['x']
        tap_y = mid_y - frame_box['y']
    else:
        tap_x, tap_y = mid_x, mid_y

    if 'prototypeInteractions' in node:
        for interaction in node['prototypeInteractions']:
            target_id = interaction.get('target')
            if target_id:
                clickables.append({
                    "name": node.get("name", "Unnamed"),
                    "from_screen": from_screen,
                    "tap_position": {"x": round(tap_x), "y": round(tap_y)},
                    "navigates_to": target_id,
                    "interaction_type": interaction.get('type', 'ON_CLICK'),
                    "node_id": node.get("id"),
                    "element_y": box['y'],
                    "screenshot": None
                })
    elif 'transitionNodeID' in node:
        clickables.append({
            "name": node.get("name", "Unnamed"),
            "from_screen": from_screen,
            "tap_position": {"x": round(tap_x), "y": round(tap_y)},
            "navigates_to": node["transitionNodeID"],
            "interaction_type": "ON_CLICK",
            "node_id": node.get("id"),
            "element_y": box['y'],
            "screenshot": None
        })

def sort_clickables(clickables, name_map, start_screen="Splash"):
    target_order_preference = {"3": 1, "2": 2}

    def sort_key(click):
        from_screen = click["from_screen"]
        target_id = str(click["navigates_to"])
        target_name = name_map.get(target_id, "Unknown").strip()

        if from_screen == start_screen:
            return (0, 0)
        elif target_name in target_order_preference:
            return (1, target_order_preference[target_name])
        else:
            return (2, click.get("element_y", 0))

    return sorted(clickables, key=sort_key)

def get_screenshot_url(token, file_key, node_id):
    headers = {'X-Figma-Token': token}
    url = f'https://api.figma.com/v1/images/{file_key}?ids={node_id}&format=png'
    response = requests.get(url, headers=headers)
    response.raise_for_status()
    return response.json().get('images', {}).get(node_id)

def download_image(url, output_path):
    if not url:
        return False
    img_data = requests.get(url).content
    with open(output_path, 'wb') as f:
        f.write(img_data)
    return True

def generate_summary(clickables, name_map):
    lines = []
    for idx, item in enumerate(clickables, 1):
        x = item['tap_position']['x']
        y = item['tap_position']['y']
        target_id = item['navigates_to']
        screen = name_map.get(target_id, "Target").strip().replace(" ", "_")
        img = os.path.basename(item.get("screenshot", f"{screen}.png"))
        lines.append(f"{idx}. Click_COORD, {x}, {y}, CHECK, {img}")
    return lines

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--token', required=True, help='Figma Token')
    parser.add_argument('--file', required=True, help='Figma File Key')
    parser.add_argument('--start', default="Splash", help='Start screen name')
    args = parser.parse_args()

    print("🔍 Fetching file...")
    data = fetch_figma_file(args.token, args.file)

    name_map, parent_map, node_lookup = {}, {}, {}
    build_node_maps(data['document'], name_map, parent_map, node_lookup)

    clickables = []
    extract_clickables(data['document'], parent_map, node_lookup, clickables)
    print(f"✅ Found {len(clickables)} clickables")

    ordered = sort_clickables(clickables, name_map, args.start)

    os.makedirs("screenshots", exist_ok=True)
    downloaded = {}
    for item in ordered:
        target_id = item["navigates_to"]
        if target_id in downloaded:
            item["screenshot"] = downloaded[target_id]
            continue

        try:
            screen_name = name_map.get(target_id, "Target").strip().replace(" ", "_")
            url = get_screenshot_url(args.token, args.file, target_id)
            file_path = f"screenshots/{screen_name}.png"
            if download_image(url, file_path):
                item["screenshot"] = file_path
                downloaded[target_id] = file_path
                print(f"📸 Saved: {file_path}")
        except Exception as e:
            print(f"⚠️ Failed to get screenshot for {target_id}: {e}")

    with open("clickable_elements.json", "w") as f:
        json.dump(ordered, f, indent=2)

    summary = generate_summary(ordered, name_map)
    with open("click_coord_summary.txt", "w") as f:
        f.write("\n".join(summary))

    print("📄 click_coord_summary.txt saved.")
    print("✅ Done.")

if __name__ == "__main__":
    main()
