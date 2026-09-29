# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from dataclasses import dataclass
from typing import Union, List
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path

from .config import SimulConfig
from .image import ImagePool
from .agent import Player
from .scene import load_scene, Scene

from .globals import NAME2PORT

# test_data = {'La Petite Maison': {'today_offering': 'The Restaurant " La Petite Maison "information as below:\n1. Customer Score: NULL\n2. Advertisement\n   Experience the exquisite flavors of France at La Petite Maison! Our culinary masters, Chef Pierre and Chef Marie, create delectable dishes using the finest ingredients. Enjoy our cozy, charming setting while savoring our signature dishes. Don\'t miss our live music evenings and exclusive weekday discounts. Join our loyalty program for exclusive rewards and benefits. Visit La Petite Maison today for an unforgettable dining journey.\n3. Menu \n   [{\'name\': \'Coq au Vin\', \'price\': 40, \'description\': \'Traditional French dish of chicken slow cooked in red wine with mushrooms and onions\'}, {\'name\': \'Bouillabaisse\', \'price\': 40, \'description\': \'Provencal fish stew served with rouille and crusty bread\'}, {\'name\': \'Ratatouille\', \'price\': 30, \'description\': \'Classic vegetable stew with eggplant, zucchini, bell peppers, and tomato\'}, {\'name\': \'Tarte Tatin\', \'price\': 30, \'description\': \'Upside-down caramelized apple tart served with a dollop of cream\'}, {\'name\': \'French Cheese Platter\', \'price\': 30, \'description\': \'Assortment of fine French cheeses served with crackers and fruits\'}, {\'name\': \'Escargot\', \'price\': 20, \'description\': \'Classic French appetizer of snails baked in garlic butter\'}]\n4. Comments\n   []\n\nPlease note that comments are merely expressions of personal opinions and are for reference only. Comments can also be time-sensitive. So, a negative comment of a restaurant does not mean it\'s not suitable for you. If you are drawn to its menu and advertisements, don\'t hesitate to give it a try.', 'dish_score': {'Coq au Vin': 0.69, 'Bouillabaisse': 0.69, 'Ratatouille': 0.72, 'Tarte Tatin': 0.72, 'French Cheese Platter': 0.72, 'Escargot': 0.61}}, 'Le Petit Gourmet': {'today_offering': 'The Restaurant " Le Petit Gourmet "information as below:\n1. Customer Score: NULL\n2. Advertisement\n   Discover the essence of French cuisine at Le Petit Gourmet! Our menu, featuring classics like Coq au Vin and Ratatouille, alongside unique French fusion dishes, promises a culinary journey through France. We use fresh, locally sourced ingredients and offer a cozy, authentic ambiance. Visit us today for an unforgettable dining experience.\n3. Menu \n   [{\'name\': \'Coq au Vin\', \'price\': 25, \'description\': \'Classic French dish of chicken slow cooked with wine, mushrooms, and garlic.\'}, {\'name\': \'Ratatouille\', \'price\': 15, \'description\': \'Traditional French vegetable stew topped with fresh herbs.\'}, {\'name\': \'Tarte Tatin\', \'price\': 10, \'description\': \'Upside-down caramelized apple tart served with whipped cream.\'}, {\'name\': \'French Onion Soup\', \'price\': 12, \'description\': \'Hearty onion soup topped with melted cheese and a toasted slice of bread.\'}, {\'name\': \'Croque Monsieur\', \'price\': 10, \'description\': \'A grilled ham and cheese sandwich with a layer of creamy béchamel sauce.\'}, {\'name\': \'Beef Bourguignon\', \'price\': 28, \'description\': \'Slow-cooked beef stew with red wine, mushrooms, and onions.\'}, {\'name\': \'Quiche Lorraine\', \'price\': 10, \'description\': \'Savory pie filled with bacon, cheese, and a creamy custard.\'}, {\'name\': \'Escargots de Bourgogne\', \'price\': 35, \'description\': \'Snails baked in a buttery garlic-parsley sauce.\'}, {\'name\': \'Salade Niçoise\', \'price\': 14, \'description\': \'Classic French salad with tuna, hard-boiled eggs, tomatoes, and olives.\'}, {\'name\': \'Crème Brûlée\', \'price\': 10, \'description\': \'Rich custard topped with a layer of hard caramel.\'}, {\'name\': \'Cheese Plate\', \'price\': 15, \'description\': \'A selection of fine French cheeses served with fresh bread and fruits.\'}]\n4. Comments\n   []\n\nPlease note that comments are merely expressions of personal opinions and are for reference only. Comments can also be time-sensitive. So, a negative comment of a restaurant does not mean it\'s not suitable for you. If you are drawn to its menu and advertisements, don\'t hesitate to give it a try.', 'dish_score': {'Coq au Vin': 0.45, 'Ratatouille': 0.44, 'Tarte Tatin': 0.46, 'French Onion Soup': 0.46, 'Croque Monsieur': 0.46, 'Beef Bourguignon': 0.46, 'Quiche Lorraine': 0.46, 'Escargots de Bourgogne': 0.51, 'Salade Niçoise': 0.46, 'Crème Brûlée': 0.46, 'Cheese Plate': 0.44}}}


# 该类负责全局的模拟过程
# 并行化运行scene，推进simulation进行.
class Simulation:
    def __init__(self, scenes: List[Scene], max_days: int = 15):
        self.scenes = scenes   
        self.curr_scene_idx = 0
        self.max_days = max(1, int(max_days))

    def get_curr_scene(self):
        return self.scenes[self.curr_scene_idx]
    
    def step(self, data):
        """
        Run one step of the simulation
        """
        current_scene = self.get_curr_scene()
        
        # Parallel run scenes & check if all scenes are finished
        max_number_parallel = 3
        with ThreadPoolExecutor(max_workers=max_number_parallel) as executor:
            futures = [executor.submit(lambda s=scene: s.run(data)) for scene in current_scene]
            # Optionally, wait for all scenes to finish and get their results
            results = [future.result() for future in futures]
        next_scene_data = current_scene[0].action_for_next_scene(results)
        
        # loop the scenes
        self.curr_scene_idx = (self.curr_scene_idx + 1) % len(self.scenes)
        
        return next_scene_data
    
    def run(self):
        """
        Main function, run the simulation
        """
        previous_scene_data = None

        for _ in range(len(self.scenes) * self.max_days):
            data = self.step(previous_scene_data)
            previous_scene_data = data
    
    @classmethod
    def from_config(cls, config: Union[str, dict, SimulConfig]):
        """
        create an simul from a config
        """
        # If config is a path, load the config
        if isinstance(config, str):
            config = SimulConfig.load(config)
        if isinstance(config, dict):
            config = SimulConfig(config)

        global_prompt = config.get("global_prompt", None)
        database_port = config.get("database_port_base", None)
        exp_name = config.get("exp_name", None)
        relationship = config.get("relationship", None)
        choice_model = config.get("choice_model", None)
        max_days = config.get("max_days", 15)
        profile_file = config.get("profile_file")
        profile_data = {"restaurants": {}, "customers": {}}
        if profile_file:
            profile_path = Path(profile_file)
            if not profile_path.is_absolute():
                profile_path = Path.cwd() / profile_path
            with profile_path.open("r", encoding="utf-8") as source:
                profile_data = json.load(source)
        restaurant_profiles = profile_data.get("restaurants", {})
        customer_preferences = profile_data.get("customers", {})
        if choice_model and customer_preferences:
            choice_model = dict(choice_model)
            choice_model["customer_preferences"] = customer_preferences

        # fill the port map, not a universal code  
        for scene_config in config.scenes:
            if scene_config['scene_type'] == 'restaurant_design':
                for player in scene_config['players']:
                    NAME2PORT[player] = database_port
                    database_port += 1
        
        # Create the players
        # Add relationship!
        players = []
        for player_config in config.players:
            # Add public_prompt to the player config
            if global_prompt is not None:
                player_config["global_prompt"] = global_prompt
            if player_config['name'] in relationship:
                player_config['relationship'] = relationship[player_config['name']]
            if player_config['name'] in restaurant_profiles:
                profile = restaurant_profiles[player_config['name']]
                player_config["role_desc"] += (
                    "\n\nAnonymized historical restaurant profile used as this "
                    "simulated restaurant's starting baseline:\n"
                    f"- Cuisine/category: {profile.get('category', 'unknown')}\n"
                    f"- City: {profile.get('city', 'unknown')}\n"
                    f"- Approximate average spend per person: RMB "
                    f"{profile.get('average_cost', 'unknown')}\n"
                    f"- Historical review count: "
                    f"{profile.get('baseline_review_count', 0)}\n"
                    f"- Historical average rating on a 0-10 scale: "
                    f"{profile.get('baseline_rating', 'unknown')}\n"
                    "Use these aggregate values as initial conditions. The "
                    "restaurant name, menu, future reviews, and future activity "
                    "are simulated, not copied from the source business."
                )
            if player_config['name'] in customer_preferences:
                profile = customer_preferences[player_config['name']]
                categories = ", ".join(profile.get("preferred_categories", [])) or "not available"
                price_reference = profile.get("price_reference")
                price_text = (
                    f"RMB {price_reference} per person"
                    if price_reference is not None else "not available"
                )
                player_config["role_desc"] += (
                    "\n\nAnonymized customer profile derived from one "
                    "randomly sampled historical reviewer (no ID or review text "
                    "is retained):\n"
                    f"- Most-reviewed cuisine categories: {categories}\n"
                    f"- Historical review count: {profile.get('history_review_count', 0)}\n"
                    f"- Personal spending reference: {price_text}\n"
                    f"- Spending reference basis: {profile.get('price_basis', 'unknown')}\n"
                    "The source does not provide reliable age, income, gender, "
                    "or personality labels; do not infer them."
                )
            player = Player.from_config(player_config)
            players.append(player)

        # Check that the player names are unique
        player_names = [player.name for player in players]
        assert len(player_names) == len(set(player_names)), "Player names must be unique"

        # Create scenes and decide their order
        scenes = []
        for scene_config in config.scenes:
            same_scene = []
            scene_config['exp_name'] = exp_name
            if scene_config['scene_type'] == 'restaurant_design' and restaurant_profiles:
                scene_config['restaurant_profiles'] = restaurant_profiles
            if scene_config['scene_type'] == 'dine' and choice_model:
                scene_config['choice_model'] = choice_model
            for i, player in enumerate(scene_config['players']):   
                scene_config['id'] = i
                # a single player or a group of players
                if isinstance(player, str):
                    assert player in player_names, f"Player {player} is not defined"
                    scene_config["players"] = [players[player_names.index(player)]]
                    scene = load_scene(scene_config)
                elif isinstance(player, list):
                    assert all(p in player_names for p in player), f"Player {player} is not defined"
                    scene_config["players"] = [players[player_names.index(p)] for p in player]
                    scene_config["scene_type"] = "group_dine"
                    scene = load_scene(scene_config)
                same_scene.append(scene)
            scenes.append(same_scene)

        return cls(scenes, max_days=max_days)
