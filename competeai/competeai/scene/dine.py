# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from typing import List
from .base import Scene
from ..agent import Player
from ..message import MessagePool
from ..globals import NAME2PORT, PORT2NAME, image_pool
from ..utils import log_table, get_data_from_database, send_data_to_database
from ..choice_model import RestaurantChoicePolicy
import json
import copy
import threading

import numpy as np
     
EXP_NAME = None
TRACE_WRITE_LOCK = threading.Lock()

processes = [
    {"name": "order", "from_db": False, "to_db": False},
    {"name": "comment", "from_db": False, "to_db": False},
    {"name": "feeling", "from_db": False, "to_db": False},
]

class Dine(Scene):
    
    type_name = "dine"
    
    def __init__(self, players: List[Player], id: int, exp_name: str, choice_model=None, **kwargs):
        super().__init__(players=players, id=id, type_name=self.type_name, **kwargs)
        
        global EXP_NAME
        EXP_NAME = exp_name
        
        self.processes = processes
        self.log_path = f"./logs/{exp_name}/{self.type_name}_{id}"
        self.message_pool = MessagePool(log_path=self.log_path)
        self.choice_policy = RestaurantChoicePolicy(choice_model) if choice_model else None
        self.trace_customer_sources = (choice_model or {}).get("trace_customer_sources", {})
        customer_preferences = (choice_model or {}).get("customer_preferences", {})
        self.customer_preferences = customer_preferences.get(players[0].name, {})
        historical_price_reference = self.customer_preferences.get("price_reference")
        self.choice_state = {
            "visit_counts": {},
            "price_reference": historical_price_reference,
            "price_observations": (
                self.customer_preferences.get("history_review_count", 0)
                if historical_price_reference is not None else 0
            ),
        }
        self.choice_result = None
        self.selected_restaurant = None
        self.experience_result = None
        self.selected_restaurant_data = None
        self.selected_dish_scores = None
        self.choice_context = None
        self.agent_outputs = {}
        self.process_attempts = {}
        self.simulation_seed = int((choice_model or {}).get("seed", 2026))
        
        self.day = 1
        self.dishes = None
        self.terminal_flag = False
    
    @classmethod
    def action_for_next_scene(cls, data):
        restaurant_list = []
        daybooks = {}
        comments = {}
        num_of_customer = {}
        infos = {}
        rival_infos = {}
        customer_choice = {}
        choice_records = []
        restaurant_round_state = {}
        round_day = None

        for value in PORT2NAME.values():
            restaurant_list.append(value)
            comments[value] = []
            daybooks[value] = {}
            num_of_customer[value] = 0
            infos[value] = ''
            rival_infos[value] = ''
            
        for d in data:
            if not isinstance(d, dict) or not d:
                continue
            agent_name = next(iter(d))
            d = d[agent_name]
            round_day = d.get("day", round_day)
            
            r_name = d["restaurant"]
            customer_choice[agent_name] = r_name
            if "choice_trace" in d:
                trace = d.get("dining_trace", {})
                choice_records.append(cls._build_trace_record(agent_name, d, trace))
            
            # if customer don't choose any restaurant, skip
            if r_name == 'None':
                continue
            
            day = d.get("day", round_day or 0)
            # construct comment
            if "comment" in d:
                comment = {"day": day, "name": agent_name, "score": d["score"], "content":  d["comment"]}
                comments[r_name].append({"type": "add", "data": comment})
              
                
            # construct daybook
            dishes = d["dishes"]
            num_of_customer[r_name] += 1
            for dish in dishes:
                if not dish in daybooks[r_name]:
                    daybooks[r_name][dish] = 0
                daybooks[r_name][dish] += 1
                
        # log customer choice
        log_path = f'./logs/{EXP_NAME}/{cls.type_name}'  # FIXME
        log_table(log_path, customer_choice, f"day{day}")
        for key in comments:
            send_data_to_database(comments[key], "comment", port=NAME2PORT[key])
        
        # construct whole daybook  
        for r_name in restaurant_list:
            show = get_data_from_database("show", port=NAME2PORT[r_name])
            candidate_snapshot = next((
                record.get("candidate_restaurant_state", {}).get(r_name)
                for record in choice_records
                if record.get("candidate_restaurant_state", {}).get(r_name)
            ), {})
            baseline_count = candidate_snapshot.get("baseline_review_count")
            baseline_rating = candidate_snapshot.get("baseline_rating")
            simulated_count = int(show.get("review_count", 0) or 0)
            simulated_rating = show.get("score")
            new_reviews = num_of_customer[r_name]
            try:
                rating_weight = int(baseline_count or 0) + simulated_count
                platform_rating_after = (
                    (float(baseline_rating or 0) * int(baseline_count or 0)
                     + float(simulated_rating or 0) * simulated_count)
                    / rating_weight
                    if rating_weight else None
                )
            except (TypeError, ValueError):
                platform_rating_after = None
            restaurant_round_state[r_name] = {
                "simulation_restaurant_instance_id": str(NAME2PORT[r_name]),
                "name": r_name,
                "source_restaurant_profile_id": candidate_snapshot.get("source_profile_id"),
                "baseline_review_count": baseline_count,
                "baseline_rating": baseline_rating,
                "simulated_review_count_after_round": simulated_count,
                "simulated_rating_after_round": simulated_rating,
                "platform_review_count_after_round": (
                    int(candidate_snapshot.get("review_count", 0) or 0) + new_reviews
                    if candidate_snapshot else None
                ),
                "platform_rating_after_round": platform_rating_after,
                "recent_diners": show.get("recent_diners"),
                "menu": show.get("menu"),
                "comments_available_after_round": len(show.get("comment", []))
                if isinstance(show.get("comment"), list) else None,
                "new_customers_this_round": num_of_customer[r_name],
                "dishes_ordered_this_round": daybooks.get(r_name, {}).get("data", {}).get("dishes", {})
                if isinstance(daybooks.get(r_name), dict) else {},
            }
            info = f"Restaurant: {r_name} \nNumber of customers: {num_of_customer[r_name]}\n Customer Comments: {show['comment']} \nMenu: {show['menu']}\n "
            infos[r_name] = info
        
        for key in daybooks:
            for r_name in restaurant_list:
                if r_name != key:
                    rival_infos[key] += infos[r_name]
            daybook = {"dishes": daybooks[key], "num_of_customer": num_of_customer[key], "rival_info": rival_infos[key]}
            
            print(f'debugging-daybook: {daybook}')
            
            daybooks[key] = {"type": "add", "data": daybook}

        # send comments and daybooks to database
        for key in daybooks:
            send_data_to_database(daybooks[key], "daybook", port=NAME2PORT[key])

        if choice_records:
            for r_name in restaurant_round_state:
                updated_show = get_data_from_database("show", port=NAME2PORT[r_name])
                restaurant_round_state[r_name]["recent_diners_after_round"] = updated_show.get("recent_diners")
            round_summary = {
                "schema_version": 1,
                "day": round_day,
                "customer_agent_count": len(choice_records),
                "completed_visits": sum(record.get("selected_restaurant") != "None" for record in choice_records),
                "restaurant_count": len(restaurant_round_state),
                "restaurant_state_after_round": restaurant_round_state,
                "trace_records_written": len(choice_records),
            }
            summary_path = f"./logs/{EXP_NAME}/round_summary.jsonl"
            with open(summary_path, "a", encoding="utf-8") as summary_log:
                summary_log.write(json.dumps(round_summary, ensure_ascii=False) + "\n")
        
        return

    @staticmethod
    def _build_trace_record(customer_name, dine_info, trace=None):
        trace = trace or dine_info.get("dining_trace", {})
        captured_outputs = {}
        for process_name, output in dine_info.get("model_outputs", {}).items():
            if process_name == "comment" and isinstance(output.get("parsed"), dict):
                parsed = {
                    "score": output["parsed"].get("score"),
                    "comment": output["parsed"].get("comment"),
                }
            else:
                parsed = copy.deepcopy(output.get("parsed"))
            captured_outputs[process_name] = {
                "raw": output.get("raw"),
                "parsed": parsed,
            }
        return {
            "schema_version": 3,
            "customer": customer_name,
            "source_customer_profile_id": trace.get("source_customer_profile_id"),
            "day": dine_info.get("day"),
            "selected_restaurant": dine_info.get("restaurant"),
            "selected_restaurant_id": trace.get("selected_restaurant_id"),
            "source_restaurant_profile_id": trace.get("source_restaurant_profile_id"),
            "selected_probability": trace.get("selected_probability"),
            "choice_trace": dine_info.get("choice_trace"),
            "choice_state_before": trace.get("choice_state_before"),
            "choice_state_after": trace.get("choice_state_after"),
            "customer_profile_signals": trace.get("customer_profile_signals"),
            "customer_portrait_snapshot": trace.get("customer_portrait_snapshot"),
            "candidate_restaurant_state": trace.get("candidate_restaurant_state"),
            "selected_dishes": dine_info.get("dishes", []),
            "experience": dine_info.get("experience"),
            "review": {"score": dine_info.get("score"), "comment": dine_info.get("comment")},
            "review_persisted": True,
            "model_outputs": captured_outputs,
            "process_attempts": dine_info.get("process_attempts", {}),
        }

    @staticmethod
    def _write_visit_trace(record):
        trace_log_path = f"./logs/{EXP_NAME}/dining_trace.jsonl"
        choice_log_path = f"./logs/{EXP_NAME}/choice_probabilities.jsonl"
        serialized = json.dumps(record, ensure_ascii=False) + "\n"
        with TRACE_WRITE_LOCK:
            with open(trace_log_path, "a", encoding="utf-8") as trace_log:
                trace_log.write(serialized)
            with open(choice_log_path, "a", encoding="utf-8") as choice_log:
                choice_log.write(serialized)
        
    def is_terminal(self):
        return self.terminal_flag

    def terminal_action(self):
        self.day += 1
        self._curr_process_idx = 0
        self.terminal_flag = False
        
        # delete all messages of system.
        self.message_pool.remove_role_messages(role="System")
    
    def move_to_next_player(self):
        self._curr_player_idx = 0  # In restaurant design, only one player
    
    def move_to_next_process(self):
        # 30% order->comment, 70% order->feeling
        if self._curr_process_idx == 0:
            if self.choice_policy:
                self._curr_process_idx += 1
            else:
                self._curr_process_idx += np.random.choice([1, 2], p=[0.3, 0.7])
        else:
            self.terminal_flag = True
    
    def prepare_for_next_step(self):
        self.move_to_next_player()
        self.move_to_next_process()
        self._curr_turn += 1
    
    # interactive step design
    def step(self, input=None):
        curr_player = self.get_curr_player()
        curr_process = self.get_curr_process()
        result = None
        
        # pre-process
        if curr_process['name'] == 'order':
            self.agent_outputs = {}
            self.process_attempts = {}
            if self.choice_policy:
                self.choice_context = {
                    "choice_state_before": {
                        "visit_counts": dict(self.choice_state["visit_counts"]),
                        "price_reference_rmb": self.choice_state["price_reference"],
                        "price_observations": self.choice_state["price_observations"],
                    },
                    "customer_profile_signals": {
                        "preferred_categories": self.customer_preferences.get("preferred_categories", []),
                        "taste_keywords": self.customer_preferences.get("taste_keywords", []),
                        "price_reference_rmb": self.customer_preferences.get("price_reference"),
                        "spice_preference": self.customer_preferences.get("spice_preference", "medium"),
                        "history_review_count": self.customer_preferences.get("history_review_count", 0),
                    "profile_confidence": self.customer_preferences.get("profile_confidence"),
                        "source_customer_profile_id": self.trace_customer_sources.get(curr_player.name),
                    },
                    "customer_profile_snapshot": self.customer_preferences,
                    "candidate_restaurant_state": {
                        name: {
                            "restaurant_id": str(info.get("restaurant_id", name)),
                            "category": info.get("category"),
                            "city": info.get("city"),
                            "average_cost_rmb": info.get("average_cost"),
                            "review_count": info.get("review_count"),
                            "recent_diners": info.get("recent_diners"),
                            "rating": info.get("rating"),
                            "baseline_review_count": info.get("baseline_review_count"),
                            "baseline_rating": info.get("baseline_rating"),
                            "source_profile_id": info.get("source_profile_id"),
                            "menu": info.get("menu", []),
                            "dish_scores": info.get("dish_score", {}),
                        }
                        for name, info in input.items()
                    },
                }
                self.choice_result = self.choice_policy.choose(
                    customer_name=curr_player.name,
                    restaurants=input,
                    visit_counts=self.choice_state["visit_counts"],
                    price_reference=self.choice_state["price_reference"],
                    preference_keywords=self.customer_preferences.get("taste_keywords", []),
                    preference_categories=self.customer_preferences.get("preferred_categories", []),
                    turn=self.day,
                    spice_preference=self.customer_preferences.get("spice_preference", "medium"),
                )
                self.selected_restaurant = self.choice_result["restaurant"]
            for k in input.keys():
                # print(input[k]['today_offering'])
                # add all today offerings to message pool
                offering = input[k]['today_offering']
                if self.choice_policy:
                    offering += (
                        f"\nPlatform signals (historical aggregate baseline plus simulated reviews): "
                        f"{input[k].get('review_count', 0)} public reviews; "
                        f"{input[k].get('recent_diners', 0)} customers in the latest three simulated rounds. "
                        "Historical review text is not included; visible comments are generated in this simulation."
                    )
                    profile_parts = [
                        value for value in (
                            input[k].get("category"),
                            input[k].get("city"),
                        ) if value
                    ]
                    if profile_parts:
                        offering += "\nHistorical starting profile: " + " / ".join(profile_parts)
                    if input[k].get("average_cost") is not None:
                        offering += (
                            f"; source-data average spend was RMB {input[k]['average_cost']} per person."
                        )
                self.add_new_prompt(player_name=curr_player.name, 
                                data=offering)
            # add order prompt
            if self.choice_policy:
                order_prompt_data = [
                    self.selected_restaurant,
                    input[self.selected_restaurant]["today_offering"]
                    + "\nCustomer preference profile (use these preferences when selecting dishes): "
                    + json.dumps(self.customer_preferences, ensure_ascii=False),
                ]
                self.add_new_prompt(
                    player_name=curr_player.name,
                    scene_name=self.type_name,
                    step_name="order_fixed",
                    data=order_prompt_data,
                )
            else:
                self.add_new_prompt(player_name=curr_player.name,
                                    scene_name=self.type_name,
                                    step_name=curr_process['name'],
                                    from_db=curr_process['from_db'])
        elif curr_process['name'] in ('comment', 'feeling'):
            # add dish score and comment prompt
            self.add_new_prompt(player_name=curr_player.name,
                                scene_name=self.type_name,
                                step_name=(
                                    'comment_fixed'
                                    if self.choice_policy and curr_process['name'] == 'comment'
                                    else curr_process['name']
                                ),
                                data=(
                                    [
                                        self.selected_restaurant,
                                        json.dumps(
                                            {
                                                "dish_ratings": input,
                                                "experience": self.experience_result,
                                                "customer_profile": self.customer_preferences,
                                            },
                                            ensure_ascii=False,
                                        ),
                                    ]
                                    if self.choice_policy and curr_process['name'] == 'comment'
                                    else input
                                ))

        # text observation
        observation_text = self.message_pool.get_visible_messages(agent_name=curr_player.name, turn=self._curr_turn)
        
        # vision observation, get two restaurant images for showing
        # if curr_process['name'] == 'order':
        #     observation_vision = image_pool.get_visible_images(restaurant_name="All")
        # else:
        observation_vision = []
        
        for i in range(self.invalid_step_retry):
            output = None
            try:
                output = curr_player(observation_text, observation_vision)
                parsed_ouput = self.parse_output(output, curr_player.name, curr_process['name'], curr_process['to_db'])
                if self.choice_policy and curr_process['name'] == 'order':
                    valid_dishes = set(input[self.selected_restaurant].get('dish_score', {}))
                    if (
                        not isinstance(parsed_ouput, dict)
                        or not isinstance(parsed_ouput.get('dishes'), list)
                        or not any(dish in valid_dishes for dish in parsed_ouput['dishes'])
                    ):
                        raise ValueError("Expected JSON with a dishes list for the preselected restaurant")
                if self.choice_policy and curr_process['name'] in ('comment', 'feeling'):
                    score = parsed_ouput.get('score') if isinstance(parsed_ouput, dict) else None
                    if (
                        not isinstance(parsed_ouput, dict)
                        or not isinstance(parsed_ouput.get('comment'), str)
                        or not parsed_ouput.get('comment').strip()
                        or isinstance(score, bool)
                        or not isinstance(score, int)
                        or not 0 <= score <= 10
                    ):
                        raise ValueError("Expected a JSON object: integer score (0-10) and non-empty string comment")
                if curr_process['name'] in ('comment', 'feeling') and not parsed_ouput:
                    raise Exception("Invalid output")
                self.agent_outputs[curr_process['name']] = {
                    "raw": output,
                    "parsed": copy.deepcopy(parsed_ouput),
                }
                self.process_attempts.setdefault(curr_process['name'], []).append({
                    "attempt": i + 1,
                    "status": "accepted",
                })
                break
            except Exception as e:
                self.process_attempts.setdefault(curr_process['name'], []).append({
                    "attempt": i + 1,
                    "status": "retry",
                    "error": str(e),
                    "raw_output": output,
                })
                print(f"Attempt {i + 1} failed with error: {e}")
        else:
            raise Exception("Invalid step retry arrived at maximum.")
        
        # post-process
        if curr_process['name'] == 'order':
            restaurant = self.selected_restaurant if self.choice_policy else parsed_ouput['restaurant']
            # error handle
            if restaurant not in input.keys() or restaurant == 'None':
                result = {self.players[0].name: {'restaurant': 'None'}}
                self.terminal_flag = True
                return result
            self.dishes = parsed_ouput['dishes']
            dish_score = input[restaurant]['dish_score']
            if self.choice_policy:
                self.selected_restaurant_data = input[restaurant]
                self.selected_dish_scores = dish_score
                self.dishes = [dish for dish in self.dishes if dish in dish_score]
                restaurant_id = str(input[restaurant].get("restaurant_id", restaurant))
                self.choice_state["visit_counts"][restaurant_id] = (
                    self.choice_state["visit_counts"].get(restaurant_id, 0) + 1
                )
                selected_prices = []
                for item in input[restaurant].get("menu", []):
                    if not isinstance(item, dict) or item.get("name") not in self.dishes:
                        continue
                    try:
                        price = float(item.get("price"))
                    except (TypeError, ValueError):
                        continue
                    if price > 0:
                        selected_prices.append(price)
                if not selected_prices:
                    price = self.choice_result["features"][restaurant]["menu_average_price"]
                    selected_prices = [price] if price is not None else []
                if selected_prices:
                    visit_price = sum(selected_prices) / len(selected_prices)
                    old_count = self.choice_state["price_observations"]
                    old_reference = self.choice_state["price_reference"] or 0.0
                    self.choice_state["price_reference"] = (
                        old_reference * old_count + visit_price
                    ) / (old_count + 1)
                    self.choice_state["price_observations"] = old_count + 1

                self.experience_result = self._simulate_visit_experience(
                    customer_name=curr_player.name,
                    restaurant_name=restaurant,
                    restaurant_data=input[restaurant],
                    dish_scores=dish_score,
                    day=self.day,
                )
            
            prompt = ''
            for dish in self.dishes:
                # check if the dish is in the restaurant
                if dish in dish_score.keys():
                    score = (
                        self.experience_result["dish_ratings"].get(dish, dish_score[dish])
                        if self.choice_policy and self.experience_result
                        else dish_score[dish]
                    )
                    prompt += f"\n{dish}: {score}"
                result = prompt
        
        if curr_process['name'] in ('comment', 'feeling'):
            dine_info = parsed_ouput
            if self.choice_policy:
                if not isinstance(dine_info, dict):
                    raw_comment = self.agent_outputs.get(curr_process['name'], {}).get("raw")
                    recovered = None
                    if isinstance(dine_info, str):
                        try:
                            recovered = json.loads(dine_info)
                        except (json.JSONDecodeError, TypeError):
                            recovered = None
                    if isinstance(recovered, dict):
                        dine_info = recovered
                    else:
                        current_score = (
                            self.experience_result.get("score", 5)
                            if isinstance(self.experience_result, dict) else 5
                        )
                        dine_info = {
                            "score": current_score,
                            "comment": raw_comment or str(parsed_ouput),
                        }
                    self.process_attempts.setdefault(curr_process['name'], []).append({
                        "status": "recovered_after_parse",
                        "reason": "non_object_comment_result",
                    })

                if not isinstance(self.experience_result, dict):
                    if self.selected_restaurant_data is not None and self.selected_dish_scores is not None:
                        self.experience_result = self._simulate_visit_experience(
                            customer_name=curr_player.name,
                            restaurant_name=self.selected_restaurant,
                            restaurant_data=self.selected_restaurant_data,
                            dish_scores=self.selected_dish_scores,
                            day=self.day,
                        )
                    else:
                        self.experience_result = {
                            "score": int(dine_info.get("score", 5)),
                            "dish_ratings": {},
                            "source": "recovered_missing_visit_experience",
                        }
                    self.process_attempts.setdefault("experience_simulation", []).append({
                        "status": "recovered",
                        "reason": "experience_result_was_not_an_object",
                    })

                # Keep the generated tone and numeric rating consistent with
                # the visit-level experience instead of letting the LLM
                # "round up" a bad visit for politeness.
                if self.experience_result:
                    dine_info["score"] = self.experience_result["score"]
                dine_info['restaurant'] = self.selected_restaurant
                dine_info['dishes'] = self.dishes
                selected_restaurant_data = self.selected_restaurant_data or {}
                selected_id = str(selected_restaurant_data.get("restaurant_id", self.selected_restaurant))
                dine_info['choice_trace'] = {
                    "probabilities": self.choice_result["probabilities"],
                    "features": self.choice_result["features"],
                    "seed": self.choice_result["seed"],
                    "turn": self.choice_result.get("turn", self.day),
                    "selected_probability": self.choice_result["probabilities"].get(self.selected_restaurant),
                    "policy_parameters": {
                        "epsilon": self.choice_policy.epsilon,
                        "exploration_floor": self.choice_policy.exploration_floor,
                        "repeat_penalty": self.choice_policy.repeat_penalty,
                        "price_penalty": self.choice_policy.price_penalty,
                        "preference_strength": self.choice_policy.preference_strength,
                        "recommendation_strength": self.choice_policy.recommendation_strength,
                        "recommendation_weights": self.choice_policy.weights,
                    },
                }
                dine_info["experience"] = self.experience_result
                state_after = {
                    "visit_counts": dict(self.choice_state["visit_counts"]),
                    "price_reference_rmb": self.choice_state["price_reference"],
                    "price_observations": self.choice_state["price_observations"],
                }
                dine_info["dining_trace"] = {
                    "selected_restaurant_id": selected_id,
                    "source_customer_profile_id": self.trace_customer_sources.get(curr_player.name),
                    "source_restaurant_profile_id": selected_restaurant_data.get("source_profile_id"),
                    "selected_probability": self.choice_result["probabilities"].get(self.selected_restaurant),
                    "choice_state_before": (self.choice_context or {}).get("choice_state_before"),
                    "choice_state_after": state_after,
                    "customer_profile_signals": (self.choice_context or {}).get("customer_profile_signals"),
                    "customer_portrait_snapshot": (self.choice_context or {}).get("customer_profile_snapshot"),
                    "candidate_restaurant_state": (self.choice_context or {}).get("candidate_restaurant_state"),
                }
                dine_info["model_outputs"] = self.agent_outputs
                dine_info["process_attempts"] = self.process_attempts
            dine_info['dishes'] = self.dishes
            dine_info['day'] = self.day
            customer_name = self.players[0].name
            if self.choice_policy and "choice_trace" in dine_info:
                self._write_visit_trace(self._build_trace_record(customer_name, dine_info))
            dine_info = {customer_name: dine_info}
            result = dine_info
                
        self.prepare_for_next_step()
        
        return result

    def _simulate_visit_experience(
        self, customer_name, restaurant_name, restaurant_data, dish_scores, day
    ):
        """Create meal-level variation separately from the platform prior."""
        import hashlib
        import random

        material = f"{self.simulation_seed}:{customer_name}:{restaurant_name}:{day}".encode()
        seed = int.from_bytes(hashlib.sha256(material).digest()[:8], "big")
        rng = random.Random(seed)
        profile = self.customer_preferences

        preference = str(profile.get("spice_preference", "medium")).lower()
        spice_tolerance = {"none": 0.05, "low": 0.25, "medium": 0.55, "high": 0.85}.get(
            preference, 0.55
        )
        dimensions = ["food", "service", "environment", "wait"]
        base_rating = float(restaurant_data.get("rating", 6.5) or 6.5)
        baselines = {
            "food": base_rating / 10,
            "service": base_rating / 10,
            "environment": base_rating / 10,
            "wait": 0.68,
        }
        # Deliberately independent day-level shocks prevent historical platform
        # reviews from dictating each individual visit.
        experience = {
            dimension: min(1.0, max(0.0, baselines[dimension] + rng.gauss(0, 0.18)))
            for dimension in dimensions
        }
        menu = restaurant_data.get("menu", []) or []
        selected_items = [
            item for item in menu
            if isinstance(item, dict) and item.get("name") in self.dishes
        ]
        spicy_items = [
            item.get("name") for item in selected_items
            if any(tag in f"{item.get('name', '')} {item.get('description', '')}".casefold()
                   for tag in ("spicy", "chili", "chilli", "hot pot", "辣"))
        ]
        if spicy_items:
            experience["food"] = min(
                1.0,
                max(0.0, experience["food"] - (1 - spice_tolerance) * rng.uniform(0.25, 0.65)),
            )
        overall = sum(experience.values()) / len(experience)
        spice_penalty = 0.0
        if spicy_items:
            spice_penalty = {
                "none": rng.uniform(2.0, 4.0),
                "low": rng.uniform(1.5, 3.2),
                "medium": rng.uniform(0.3, 1.5),
                "high": 0.0,
            }.get(preference, 0.8)
        score = min(
            10,
            max(0, int(round(overall * 10 + rng.gauss(0, 0.8) - spice_penalty))),
        )
        dish_ratings = {}
        for item in selected_items:
            original = float(dish_scores.get(item["name"], 0.6) or 0.6)
            dish_value = min(1.0, max(0.0, original + rng.gauss(0, 0.14)))
            if item["name"] in spicy_items:
                dish_value = min(1.0, max(0.0, dish_value - (1 - spice_tolerance) * 0.35))
            dish_ratings[item["name"]] = round(dish_value, 2)
        directness = profile.get("expression_directness", 0.5)
        style = profile.get("expression_style", "natural")
        return {
            "dimensions": {key: round(value, 2) for key, value in experience.items()},
            "score": score,
            "dish_ratings": dish_ratings,
            "spice_preference": preference,
            "spicy_dishes": spicy_items,
            "spice_mismatch_penalty": round(spice_penalty, 2),
            "expression_directness": directness,
            "expression_style": style,
            "visit_seed": seed,
            "source": "simulated_visit_variation_not_observed_offline_data",
        }
