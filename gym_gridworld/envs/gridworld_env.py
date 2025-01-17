import gym
import sys
import os
import time
import copy
from gym import error, spaces, utils
from gym.utils import seeding
import numpy as np
from PIL import Image as Image
import matplotlib.pyplot as plt
import random
from pdb import set_trace
import pickle
import itertools
import sys
import collections
import json

# define colors
# 0: black; 1 : gray; 2 : blue; 3 : green; 4 : red
COLORS = {0: [0.0, 0.0, 0.0], 1: [0.5, 0.5, 0.5], \
          2: [1.0, 0.0, 0.0], 3: [0.0, 1.0, 0.0], \
          4: [1.0, 0.0, 0.0], 6: [1.0, 0.0, 1.0], \
          7: [1.0, 1.0, 0.0], 8: [1.0, 0.0, 0.0],
          9: [1.0, 0.0, 0.0], 10: [1.0, 0.0, 0.0]}


class GridworldEnv(gym.Env):
    metadata = {'render.modes': ['human']}
    num_env = 0

    def __init__(self):
        print('initializing environment')
        self._seed = 0
        self.model = None
        self.levels_count = 0  # count of each 100 levels
        self.actions = [0, 1, 2, 3]
        self.action_space = spaces.Discrete(4)
        self.action_pos_dict = [[-1, 0], [1, 0], [0, -1], [0, 1]]
        self.total_steps_counter = 0
        self.steps = []
        self.step_counter = 0
        self.level_counter = 0
        self.data = {'game_type': [], 'player': [], 'map': [], 'level': [], 'self_start_loc': [], 'ns_start_locs': [],
                     'reward_loc': [], 'self_actions': [], 'self_locs': [], 'ns_locs': [], 'wall_interactions': [],
                     'ns_interactions': [], 'steps': []}

        ''' set observation space '''
        self.obs_shape = [128, 128, 3]  # observation space shape
        self.observation_space = spaces.Box(low=0, high=1, shape=self.obs_shape, dtype=np.float32)
        P = {
            'policy': 'MlpPolicy',
            'seed': 0,
            'env_id': 'gridworld-v0',
            'singleAgent': False,
            'game_type': 'logic',  # logic or contingency or change_agent
            'player': 'a2c_training',  # random, human, dqn_training, self_class, ppo2_training
            'exp_name': 'train_',
            'verbose': False,
            'n_levels': 100,
            'shuffle_keys': False,
            'log_neptune': False,
            'data_save_dir': None,
            'load': False,  # Load pretrained agent
            'timestamp': 100,  # Select which weight to run. Enter -1 for the latest.
            'save': False,  # Save the weights
            'levels_count': 20,  # Stop until 100 * 'levels_count' levels
            'load_game': None,  # Which weights to load
            'agent_location_random': True,  # Is agent location random or not
            'n_timesteps': 10000,
            'single_loc': False,
        }
        self.make_game(P)

    def make_game(self, P):
        '''
        Initialize env properties, given game type, player, and no. agents
        Normally the contents of this function would be in init, but we can't add arguments to openai's init method.
        '''

        self.metadata = P
        self._seed = P['seed']

        # self.metadata['env_seed'] = self._seed
        self.game_type = P['game_type']
        self.player = P['player']
        self.exp_name = P['exp_name']
        self.singleAgent = P['singleAgent']
        self.verbose = P['verbose']
        self.log_neptune = P['log_neptune']
        self.n_levels = P['n_levels']
        self.single_loc = P['single_loc']
        self.shuffle_keys = P['shuffle_keys']
        self.agent_location_random = P['agent_location_random']
        self.this_file_path = os.path.dirname(os.path.realpath(__file__))

        if self.verbose:
            print('making environment')

        ''' set game_type-specific env config '''
        if self.game_type == 'logic' or self.game_type == 'logic_extended':
            self.agent_start_locs = [[1, 1], [1, 7], [7, 1], [7, 7]]
            self.grid_map_path = os.path.join(self.this_file_path,
                                              self.game_type + '/plan' + str(random.randint(0, 9)) + '.txt')
        elif self.game_type == 'contingency' or self.game_type == 'change_agent':
            self.agent_start_locs = [[6, 6], [6, 14], [14, 6], [14, 14]]
            self.grid_map_path = os.path.join(self.this_file_path, self.game_type + '/plan0.txt')
            self.perim = 3
            # self.oscil_dirs = [1,0,0]
            self.oscil_dirs = [random.randint(0, 1), random.randint(0, 1),
                               random.randint(0, 1)]  # whether to oscil ud (0) or lr (1)
            if self.shuffle_keys:
                random.shuffle(self.action_pos_dict)  # distort key mappings for self sprite

        ''' initialize system state '''
        self.start_grid_map = self._read_grid_map(self.grid_map_path)  # initial grid map

        ''' reset agent location '''

        if not self.agent_location_random:
            new_s_loc = self.agent_start_locs[0]
        else:
            new_s_loc = self.agent_start_locs[random.randint(0, 3)]
        self.start_grid_map[new_s_loc[0], new_s_loc[1]] = 4

        self.current_grid_map = copy.deepcopy(self.start_grid_map)  # current grid map
        self.observation = self._gridmap_to_observation(self.start_grid_map)
        self.grid_map_shape = self.start_grid_map.shape

        ''' agent state: start, target, current state '''
        self.self_start_state, self.ns_start_states, self.agent_target_state = self._get_agent_start_target_state(
            self.start_grid_map)
        self.s_state = copy.deepcopy(self.self_start_state)

        ''' set other parameters '''
        self.restart_once_done = False  # restart or not once done

        GridworldEnv.num_env += 1
        self.this_fig_num = GridworldEnv.num_env
        if self.verbose == 1:
            self.fig = plt.figure(self.this_fig_num)
            plt.show(block=False)
            plt.axis('off')
            self._render()

    def step(self, action):
        if self.verbose:
            print('taking a step')
        if self.game_type == 'logic' or self.game_type == 'logic_extended':
            new_obs, rew, done, info = self.step_logic(action)
        elif self.game_type == 'contingency':
            new_obs, rew, done, info = self.step_contingency(action)
        elif self.game_type == 'change_agent':
            new_obs, rew, done, info = self.step_change_agent(action)

        return new_obs, rew, done, info

    def step_logic(self, action):
        self.total_steps_counter += 1
        self.step_counter += 1

        ''' return next observation, reward, finished, success '''
        action = int(action)
        info = {}
        info['success'] = False

        ''' append level-specific data '''
        self.level_self_actions.append(action)
        self.level_s_locs.append(self.s_state)
        self.level_ns_locs.append(self.ns_states)

        # Update agent position(s)
        nxt_s_state = (self.s_state[0] + self.action_pos_dict[action][0],
                       self.s_state[1] + self.action_pos_dict[action][1])

        # Get next observation, reward, win state, and info
        # if action == 0: # stay in place
        #     info['success'] = True
        #     return (self.observation, 0, False, info)
        if nxt_s_state[0] < 0 or nxt_s_state[0] >= self.grid_map_shape[0]:
            info['success'] = False
            return (self.observation, 0, False, info)
        if nxt_s_state[1] < 0 or nxt_s_state[1] >= self.grid_map_shape[1]:
            info['success'] = False
            return (self.observation, 0, False, info)

        # successful behavior
        org_s_color = self.current_grid_map[self.s_state[0], self.s_state[1]]
        new_s_color = self.current_grid_map[nxt_s_state[0], nxt_s_state[1]]
        if (new_s_color == 0):
            if org_s_color == 4:
                self.current_grid_map[self.s_state[0], self.s_state[1]] = 0
                self.current_grid_map[nxt_s_state[0], nxt_s_state[1]] = 4
            elif org_s_color == 6 or org_s_color == 7:
                self.current_grid_map[self.s_state[0], self.s_state[1]] = org_s_color - 4
                self.current_grid_map[nxt_s_state[0], nxt_s_state[1]] = 4
            self.s_state = copy.deepcopy(nxt_s_state)
        elif (new_s_color == 1) | (new_s_color == 8):  # gray or red (non-self agent)
            if new_s_color == 1:
                self.wall_interactions += 1
            elif new_s_color == 8:
                self.ns_interactions += 1
            info['success'] = False
        elif new_s_color == 2 or new_s_color == 3:
            self.current_grid_map[self.s_state[0], self.s_state[1]] = 0
            self.current_grid_map[nxt_s_state[0], nxt_s_state[1]] = new_s_color + 4
            self.s_state = copy.deepcopy(nxt_s_state)
        self.observation = self._gridmap_to_observation(self.current_grid_map)
        self._render()
        if nxt_s_state[0] == self.agent_target_state[0] and nxt_s_state[1] == self.agent_target_state[1]:
            target_observation = copy.deepcopy(self.observation)
            if self.restart_once_done:
                self.observation = self.reset()
                info['success'] = True
                return (self.observation, 1, True, info)
            else:
                info['success'] = True
                return (target_observation, 1, True, info)
        else:
            info['success'] = True
            return (self.observation, 0, False, info)

    def step_contingency(self, action):
        self.total_steps_counter += 1
        self.step_counter += 1
        info = {}
        info['success'] = False
        osc_directions = [-1, 1]
        new_ns_colors = [0, 0, 0]

        ''' next self position and colors '''
        action = int(action)
        self.level_self_actions.append(action)

        ''' append level-specific data '''
        # self.level_self_actions.append(action) <-
        self.level_s_locs.append(self.s_state)
        self.level_ns_locs.append(self.ns_states)

        nxt_s_state = (self.s_state[0] + self.action_pos_dict[action][0],
                       self.s_state[1] + self.action_pos_dict[action][1])

        ''' next non-self positions and colors '''
        nxt_ns_actions = [random.sample(osc_directions, 1)[0], random.sample(osc_directions, 1)[0],
                          random.sample(osc_directions, 1)[0]]
        nxt_ns_states = copy.deepcopy(self.ns_states)
        for i, agent in enumerate(self.ns_states):

            if self.oscil_dirs[i] == 0:  # if agent oscillates up-down
                nxt_ns_states[i][0] = self.ns_states[i][0] + nxt_ns_actions[i]
                if nxt_ns_states[i] == [self.ns_lim[i][0][0] - 1, self.ns_lim[i][0][1]]:  # if equal to upper limit
                    nxt_ns_states[i][0] = nxt_ns_states[i][0] + 2
                if nxt_ns_states[i] == [self.ns_lim[i][1][0] + 1, self.ns_lim[i][1][1]]:  # if equal to lower limit
                    nxt_ns_states[i][0] = nxt_ns_states[i][0] - 2
                new_ns_colors[i] = self.current_grid_map[nxt_ns_states[i][0], nxt_ns_states[i][1]]

            elif self.oscil_dirs[i] == 1:  # ditto, if agent oscillates left-right
                nxt_ns_states[i][1] = self.ns_states[i][1] + nxt_ns_actions[i]
                if nxt_ns_states[i] == [self.ns_lim[i][2][0], self.ns_lim[i][2][1] - 1]:  # if equal to left limit
                    nxt_ns_states[i][1] = nxt_ns_states[i][1] + 2
                if nxt_ns_states[i] == [self.ns_lim[i][3][0], self.ns_lim[i][3][1] + 1]:  # if equal to right limit
                    nxt_ns_states[i][1] = nxt_ns_states[i][1] - 2
                new_ns_colors[i] = self.current_grid_map[nxt_ns_states[i][0], nxt_ns_states[i][1]]

            ''' update grid locations of non-self agents '''
            # since we determine next position for ns first, we need to also check if self is planning to enter a common square
            # also need to check that we're not entering the self's current state, in case the self decides not to move
            num_prev_agents = len(np.transpose(np.nonzero((self.current_grid_map == 8) | (self.current_grid_map == 4))))
            if (new_ns_colors[i] != 4) & (nxt_ns_states[i] != nxt_s_state) & (nxt_ns_states[i] != self.s_state):
                self.current_grid_map[self.ns_states[i][0], self.ns_states[i][1]] = 0
                self.current_grid_map[nxt_ns_states[i][0], nxt_ns_states[i][1]] = 8
                self.ns_states[i] = copy.deepcopy(
                    nxt_ns_states[i])  # only update agent state if grid is changed; on per agent basis

        org_s_color = self.current_grid_map[self.s_state[0], self.s_state[1]]
        new_s_color = self.current_grid_map[nxt_s_state[0], nxt_s_state[1]]

        ''' unsuccessful behavior: self has no action, or attempts to move out-of-bounds. Do nothing '''
        # if action == 0: # stay in place
        #     self.observation = self._gridmap_to_observation(self.current_grid_map)
        #     self._render()
        #     info['success'] = True
        #     return (self.observation, 0, False, info)
        if nxt_s_state[0] < 0 or nxt_s_state[0] >= self.grid_map_shape[0]:  # stay in place
            info['success'] = False
            return (self.observation, 0, False, info)
        if nxt_s_state[1] < 0 or nxt_s_state[1] >= self.grid_map_shape[1]:  # stay in place
            info['success'] = False
            return (self.observation, 0, False, info)

        ''' successful behavior: update self grid state'''
        if new_s_color == 0:
            if org_s_color == 4:
                num_prev_agents = len(
                    np.transpose(np.nonzero((self.current_grid_map == 8) | (self.current_grid_map == 4))))
                self.current_grid_map[self.s_state[0], self.s_state[1]] = 0
                self.current_grid_map[nxt_s_state[0], nxt_s_state[1]] = 4

            elif org_s_color == 6 or org_s_color == 7:
                num_prev_agents = len(
                    np.transpose(np.nonzero((self.current_grid_map == 8) | (self.current_grid_map == 4))))
                self.current_grid_map[self.s_state[0], self.s_state[1]] = org_s_color - 4
                self.current_grid_map[nxt_s_state[0], nxt_s_state[1]] = 4

            self.s_state = copy.deepcopy(nxt_s_state)
            self.agent_states = np.transpose(np.nonzero((self.current_grid_map == 8) | (self.current_grid_map == 4)))
        elif (new_s_color == 1) | (new_s_color == 8):  # gray or red (non-self agent)
            if new_s_color == 1:
                self.wall_interactions += 1
            elif new_s_color == 8:
                self.ns_interactions += 1
            info['success'] = False
        elif new_s_color == 2 or new_s_color == 3:
            self.current_grid_map[self.s_state[0], self.s_state[1]] = 0
            self.current_grid_map[nxt_s_state[0], nxt_s_state[1]] = new_s_color + 4
            self.s_state = copy.deepcopy(nxt_s_state)
            self.agent_states = np.transpose(np.nonzero((self.current_grid_map == 8) | (self.current_grid_map == 4)))
        self.observation = self._gridmap_to_observation(self.current_grid_map)
        self._render()
        if nxt_s_state[0] == self.agent_target_state[0] and nxt_s_state[1] == self.agent_target_state[1]:
            target_observation = copy.deepcopy(self.observation)
            if self.restart_once_done:
                self.observation = self.reset()
                info['success'] = True
                return (self.observation, 1, True, info)
            else:
                info['success'] = True
                return (target_observation, 1, True, info)
        else:
            info['success'] = True
            return (self.observation, 0, False, info)

    ''' change the self to another possible self every 7 steps '''

    def change_agent(self):
        if self.step_counter % 7 != 0:
            return
        rand_num = random.randint(0, 2)
        temp = self.s_state
        self.current_grid_map[temp[0], temp[1]] = 0
        self.s_state = list(self.ns_states[rand_num])
        print("AGENT CHANGED. Current agent: ", self.s_state)
        self.current_grid_map[self.s_state[0], self.s_state[1]] = 4

        self.ns_states[rand_num] = [int(temp[0]), int(temp[1])]

    def step_change_agent(self, action):
        if self.step_counter != 0:
            self.change_agent()
        self.total_steps_counter += 1
        self.step_counter += 1
        info = {}
        info['success'] = False
        osc_directions = [-1, 1]
        new_ns_colors = [0, 0, 0]

        ''' next self position and colors '''
        action = int(action)
        self.level_self_actions.append(action)

        ''' append level-specific data '''
        self.level_s_locs.append(self.s_state)
        self.level_ns_locs.append(self.ns_states)

        nxt_s_state = (self.s_state[0] + self.action_pos_dict[action][0],
                       self.s_state[1] + self.action_pos_dict[action][1])

        nxt_ns_states = copy.deepcopy(self.ns_states)

        for i, agent in enumerate(self.ns_states):
            oscil_dir = self.oscil_dirs[i]
            action = random.randint(0, 1) if oscil_dir else random.randint(2, 3)
            next_color = self.current_grid_map[nxt_ns_states[i][0] + self.action_pos_dict[action][0],
                                               nxt_ns_states[i][1] + self.action_pos_dict[action][1]]

            # move non selves without colliding to anything
            cc = [0] * 4
            stay = False
            while next_color == 1 or next_color == 3 or next_color == 8:
                action = random.randint(0, 1) if oscil_dir else random.randint(2, 3)

                if cc[0] != 0 and cc[1] != 0 and cc[2] != 0 and cc[3] != 0:  # Cannot move, stay
                    nxt_ns_states[i] = self.ns_states[i]
                    stay = True
                    break

                if cc[action] == 0:  # if current action is not tried before
                    cc[action] = cc[action] + 1
                    next_color = self.current_grid_map[nxt_ns_states[i][0] + self.action_pos_dict[action][0],
                                                       nxt_ns_states[i][1] + self.action_pos_dict[action][1]]

            # Update ns positions
            if stay is False:
                nxt_ns_states[i][0] = nxt_ns_states[i][0] + self.action_pos_dict[action][0]
                nxt_ns_states[i][1] = nxt_ns_states[i][1] + self.action_pos_dict[action][1]
            new_ns_colors[i] = self.current_grid_map[nxt_ns_states[i][0], nxt_ns_states[i][1]]

            ''' update grid locations of non-self agents '''
            # since we determine next position for ns first, we need to also check if self is planning to enter a common square
            # also need to check that we're not entering the self's current state, in case the self decides not to move
            num_prev_agents = len(np.transpose(np.nonzero((self.current_grid_map == 8) | (self.current_grid_map == 4))))
            if (new_ns_colors[i] != 4) & (nxt_ns_states[i] != nxt_s_state) & (nxt_ns_states[i] != self.s_state):
                self.current_grid_map[self.ns_states[i][0], self.ns_states[i][1]] = 0
                self.current_grid_map[nxt_ns_states[i][0], nxt_ns_states[i][1]] = 8
                self.ns_states[i] = copy.deepcopy(
                    nxt_ns_states[i])  # only update agent state if grid is changed; on per agent basis

        org_s_color = self.current_grid_map[self.s_state[0], self.s_state[1]]
        new_s_color = self.current_grid_map[nxt_s_state[0], nxt_s_state[1]]

        ''' unsuccessful behavior: self has no action, or attempts to move out-of-bounds. Do nothing '''
        # if action == 0: # stay in place
        #     self.observation = self._gridmap_to_observation(self.current_grid_map)
        #     self._render()
        #     info['success'] = True
        #     return (self.observation, 0, False, info)
        if nxt_s_state[0] < 0 or nxt_s_state[0] >= self.grid_map_shape[0]:  # stay in place
            info['success'] = False
            return (self.observation, 0, False, info)
        if nxt_s_state[1] < 0 or nxt_s_state[1] >= self.grid_map_shape[1]:  # stay in place
            info['success'] = False
            return (self.observation, 0, False, info)

        ''' successful behavior: update self grid state'''
        if new_s_color == 0:
            if org_s_color == 4:
                num_prev_agents = len(
                    np.transpose(np.nonzero((self.current_grid_map == 8) | (self.current_grid_map == 4))))
                self.current_grid_map[self.s_state[0], self.s_state[1]] = 0
                self.current_grid_map[nxt_s_state[0], nxt_s_state[1]] = 4

            elif org_s_color == 6 or org_s_color == 7:
                num_prev_agents = len(
                    np.transpose(np.nonzero((self.current_grid_map == 8) | (self.current_grid_map == 4))))
                self.current_grid_map[self.s_state[0], self.s_state[1]] = org_s_color - 4
                self.current_grid_map[nxt_s_state[0], nxt_s_state[1]] = 4

            self.s_state = copy.deepcopy(nxt_s_state)
            self.agent_states = np.transpose(np.nonzero((self.current_grid_map == 8) | (self.current_grid_map == 4)))
        elif (new_s_color == 1) | (new_s_color == 8):  # gray or red (non-self agent)
            if new_s_color == 1:
                self.wall_interactions += 1
            elif new_s_color == 8:
                self.ns_interactions += 1
            info['success'] = False
        elif new_s_color == 2 or new_s_color == 3:
            self.current_grid_map[self.s_state[0], self.s_state[1]] = 0
            self.current_grid_map[nxt_s_state[0], nxt_s_state[1]] = new_s_color + 4
            self.s_state = copy.deepcopy(nxt_s_state)
            self.agent_states = np.transpose(np.nonzero((self.current_grid_map == 8) | (self.current_grid_map == 4)))
        self.observation = self._gridmap_to_observation(self.current_grid_map)
        self._render()
        if nxt_s_state[0] == self.agent_target_state[0] and nxt_s_state[1] == self.agent_target_state[1]:
            target_observation = copy.deepcopy(self.observation)
            if self.restart_once_done:
                self.observation = self.reset()
                info['success'] = True
                return (self.observation, 1, True, info)
            else:
                info['success'] = True
                return (target_observation, 1, True, info)
        else:
            info['success'] = True
            return (self.observation, 0, False, info)

    def get_ns_limits(self):
        self.ns_lim = [[], [], []]
        for i, agent in enumerate(self.ns_states):
            self.ns_lim[i] = [[agent[0] - self.perim, agent[1]],
                              [agent[0] + self.perim, agent[1]],
                              [agent[0], agent[1] - self.perim],
                              [agent[0], agent[1] + self.perim]
                              ]

    def reset(self):
        if self.verbose:
            print('reset environment')
        ''' save data '''
        # if self.step_counter > 50000000:
        #    print('step count too high. terminating...')
        #    sys.exit()

        if self.level_counter >= 0 and self.step_counter != 0:

            if self.level_counter == 0:
                self.data['game_type'].append(self.game_type)
                self.data['player'].append(self.player)

            self.data['map'].append(self.start_grid_map.tolist())
            self.data['level'].append(self.level_counter)
            self.data['self_start_loc'].append(np.transpose(self.self_start_state).tolist())  #
            self.data['ns_start_locs'].append(self.ns_start_states)
            self.data['reward_loc'].append(np.transpose(self.agent_target_state).tolist())
            self.data['self_actions'].append(self.level_self_actions)
            self.data['self_locs'].append(np.transpose(self.level_s_locs).tolist())
            self.data['ns_locs'].append(self.level_ns_locs)
            self.data['wall_interactions'].append(self.wall_interactions)
            self.data['ns_interactions'].append(self.ns_interactions)
            self.data['steps'].append(self.step_counter)

            print('level: ', self.level_counter)
            print('steps array: ', self.data['steps'])
            print('total steps: ', self.total_steps_counter)

            self.level_counter += 1

        if self.log_neptune:
            # self.exp_neptune.log_metric('steps', self.step_counter)
            self.exp_neptune.log_text(self.data)

        ''' print some metrics '''
        self.level_self_actions = []  # clear actions for this level
        self.level_s_locs = []
        self.level_ns_locs = []
        self.wall_interactions = 0
        self.ns_interactions = 0

        self.step_counter = 0

        ''' save data when all levels are completed '''
        if self.level_counter == self.n_levels:
            final_data = {}
            final_data['data'] = self.data
            final_data['metadata'] = self.metadata

            # with open('data/' + self.player + '_' + str(self.exp_name) + '.pkl', 'wb') as f:
            #    pickle.dump(self.steps[2:], f)

            if not os.path.exists(self.metadata['data_save_dir']):
                os.makedirs(self.metadata['data_save_dir'])

            with open(
                    self.metadata['data_save_dir'] + self.metadata['exp_name'] + str(self.levels_count * 100) + ".json",
                    'w')  as fp:
                json.dump(final_data, fp)
                print('******* CONGRATS, YOU FINISHED ' + str(self.levels_count) + ' WITH ' + str(
                    self.total_steps_counter) + ' STEPS !************')

                self.levels_count += 1
                if self.levels_count == self.metadata['levels_count']:
                    path = self.metadata['save_path'] + "lastSave/weights"

                    if not os.path.exists(path):
                        os.makedirs(path)

                    if self.model is not None:
                        self.model.save(path)
                    sys.exit(0)

                # reset variables
                self.data = {'game_type': [], 'player': [], 'map': [], 'level': [], 'self_start_loc': [],
                             'ns_start_locs': [],
                             'reward_loc': [], 'self_actions': [], 'self_locs': [], 'ns_locs': [],
                             'wall_interactions': [],
                             'ns_interactions': [], 'steps': []}
                self.level_counter = 0
                self.level_self_actions = []  # clear actions for this level
                self.level_s_locs = []
                self.level_ns_locs = []
                self.steps = []
                # sys.exit(0)

        ''' get new self location '''
        if self.game_type == 'logic' or self.game_type == 'logic_extended':
            self.grid_map_path = os.path.join(self.this_file_path,
                                              self.game_type + '/plan' + str(random.randint(0, 9)) + '.txt')
        elif self.game_type == 'contingency' or self.game_type == 'change_agent':
            self.grid_map_path = os.path.join(self.this_file_path, self.game_type + '/plan0.txt')
            if self.shuffle_keys and self.levels_count % 2 == 0:  # Shuffle each 200 levels
                random.shuffle(self.action_pos_dict)  # distort key mappings for self sprite

        ''' if singleAgent is true, blank out all non-self agents '''
        if self.singleAgent == True:
            for loc in self.agent_start_locs:
                self.start_grid_map[loc[0], loc[1]] = 0

        ''' reset grid state and agent location '''
        self.start_grid_map = self._read_grid_map(self.grid_map_path)  # initial grid map
        if not self.agent_location_random:
            new_s_loc = self.agent_start_locs[0]
        else:
            new_s_loc = self.agent_start_locs[random.randint(0, 3)]

        if self.single_loc == True:
            self.start_grid_map[self.agent_start_locs[0]] = 4
        else:
            self.start_grid_map[new_s_loc[0], new_s_loc[1]] = 4

        ''' update states '''
        self.self_start_state, self.ns_start_states, self.agent_target_state = self._get_agent_start_target_state(
            self.start_grid_map)
        self.s_state = copy.deepcopy(self.self_start_state)
        self.ns_states = np.transpose(np.nonzero((self.start_grid_map == 8))).tolist()

        self.current_grid_map = copy.deepcopy(self.start_grid_map)
        self.observation = self._gridmap_to_observation(self.start_grid_map)
        if self.game_type == 'contingency' or self.game_type == 'change_agent':
            self.get_ns_limits()  # get new oscillation limits for non-self agents

        self.current_grid_map
        self._render()

        return self.observation

    def _read_grid_map(self, grid_map_path):
        with open(grid_map_path, 'r') as f:
            grid_map = f.readlines()
        grid_map_array = np.array(
            list(map(
                lambda x: list(map(
                    lambda y: int(y),
                    x.split(' ')
                )),
                grid_map
            ))
        )
        return grid_map_array

    def _get_agent_start_target_state(self, start_grid_map):
        '''
        Return agent (=4) starting location and current goal (=3) location. If 4 and 3 dont' exist, throw error.
        '''

        start_state = None
        target_state = None
        agent_states = []
        start_state = list(map(
            lambda x: x[0] if len(x) > 0 else None,
            np.where(start_grid_map == 4)
        ))
        target_state = list(map(
            lambda x: x[0] if len(x) > 0 else None,
            np.where(start_grid_map == 3)
        ))

        self.agent_states = np.transpose(np.nonzero((start_grid_map == 8) | (start_grid_map == 4)))
        self.ns_states = np.transpose(np.nonzero((start_grid_map == 8))).tolist()
        self.available_states = np.transpose(np.nonzero(start_grid_map == 0))

        if start_state == [None, None] or target_state == [None, None]:
            sys.exit('Start or target state not specified')
        return start_state, self.ns_states, target_state

    def _gridmap_to_observation(self, grid_map, obs_shape=None):
        if obs_shape is None:
            obs_shape = self.obs_shape
        observation = np.zeros(obs_shape, dtype=np.float32)
        gs0 = int(observation.shape[0] / grid_map.shape[0])
        gs1 = int(observation.shape[1] / grid_map.shape[1])
        for i in range(grid_map.shape[0]):
            for k in range(grid_map.shape[1]):
                observation[i * gs0:(i + 1) * gs0, k * gs1:(k + 1) * gs1] = np.array(COLORS[grid_map[i, k]])
        return observation

    def _render(self):
        if self.verbose != 1:
            return
        img = self.observation
        fig = plt.figure(self.this_fig_num, figsize=(3, 4))  # figsize=(3,4)
        actionDict = {0: "UP", 1: "DOWN", 2: "LEFT", 3: "RIGHT"}

        plt.clf()
        plt.imshow(img)

        if self.step_counter != 0:
            plt.title(actionDict[self.level_self_actions[self.step_counter - 1]])

        if self.step_counter != 0 and self.game_type == "change_agent" and self.step_counter % 7 == 0:
            plt.suptitle("CHANGE")

        fig.canvas.draw()
        plt.pause(0.000001)
        return

    def change_start_state(self, sp):
        ''' change agent start state '''
        ''' Input: sp: new start state '''
        if self.self_start_state[0] == sp[0] and self.self_start_state[1] == sp[1]:
            _ = self.reset()
            return True
        elif self.start_grid_map[sp[0], sp[1]] != 0:
            return False
        else:
            s_pos = copy.deepcopy(self.self_start_state)
            self.start_grid_map[s_pos[0], s_pos[1]] = 0
            self.start_grid_map[sp[0], sp[1]] = 4
            self.current_grid_map = copy.deepcopy(self.start_grid_map)
            self.self_start_state = [sp[0], sp[1]]
            self.observation = self._gridmap_to_observation(self.current_grid_map)
            self.s_state = copy.deepcopy(self.self_start_state)
            self.reset()
            self._render()
        return True

    def change_target_state(self, tg):
        if self.agent_target_state[0] == tg[0] and self.agent_target_state[1] == tg[1]:
            _ = self.reset()
            return True
        elif self.start_grid_map[tg[0], tg[1]] != 0:
            return False
        else:
            t_pos = copy.deepcopy(self.agent_target_state)
            self.start_grid_map[t_pos[0], t_pos[1]] = 0
            self.start_grid_map[tg[0], tg[1]] = 3
            self.current_grid_map = copy.deepcopy(self.start_grid_map)
            self.agent_target_state = [tg[0], tg[1]]
            self.observation = self._gridmap_to_observation(self.current_grid_map)
            self.s_state = copy.deepcopy(self.self_start_state)
            self.reset()
            self._render()
        return True

    def get_grid_state(self):
        ''' get current grid state '''
        return self.current_grid_map, self.available_states, self.agent_states, self.agent_target_state, self.ns_states, self.s_state

    def get_agent_state(self):
        ''' get current agent state '''
        return self.s_state

    def get_start_state(self):
        ''' get current start state '''
        return self.self_start_state

    def get_target_state(self):
        ''' get current target state '''
        return self.agent_target_state

    def _jump_to_state(self, to_state):
        ''' move agent to another state '''
        info = {}
        info['success'] = True
        if self.current_grid_map[to_state[0], to_state[1]] == 0:
            if self.current_grid_map[self.s_state[0], self.s_state[1]] == 4:
                self.current_grid_map[self.s_state[0], self.s_state[1]] = 0
                self.current_grid_map[to_state[0], to_state[1]] = 4
                self.observation = self._gridmap_to_observation(self.current_grid_map)
                self.s_state = [to_state[0], to_state[1]]
                self._render()
                return (self.observation, 0, False, info)
            if self.current_grid_map[self.s_state[0], self.s_state[1]] == 6:
                self.current_grid_map[self.s_state[0], self.s_state[1]] = 2
                self.current_grid_map[to_state[0], to_state[1]] = 4
                self.observation = self._gridmap_to_observation(self.current_grid_map)
                self.s_state = [to_state[0], to_state[1]]
                self._render()
                return (self.observation, 0, False, info)
            if self.current_grid_map[self.s_state[0], self.s_state[1]] == 7:
                self.current_grid_map[self.s_state[0], self.s_state[1]] = 3
                self.current_grid_map[to_state[0], to_state[1]] = 4
                self.observation = self._gridmap_to_observation(self.current_grid_map)
                self.s_state = [to_state[0], to_state[1]]
                self._render()
                return (self.observation, 0, False, info)
        elif self.current_grid_map[to_state[0], to_state[1]] == 4:
            return (self.observation, 0, False, info)
        elif self.current_grid_map[to_state[0], to_state[1]] == 1:
            info['success'] = False
            return (self.observation, 0, False, info)
        elif self.current_grid_map[to_state[0], to_state[1]] == 3:
            self.current_grid_map[self.s_state[0], self.s_state[1]] = 0
            self.current_grid_map[to_state[0], to_state[1]] = 7
            self.s_state = [to_state[0], to_state[1]]
            self.observation = self._gridmap_to_observation(self.current_grid_map)
            self._render()
            if self.restart_once_done:
                self.observation = self.reset()
                return (self.observation, 1, True, info)
            return (self.observation, 1, True, info)
        else:
            info['success'] = False
            return (self.observation, 0, False, info)

    def _close_env(self):
        plt.close(1)
        return

    def jump_to_state(self, to_state):
        a, b, c, d = self._jump_to_state(to_state)
        return (a, b, c, d)

    def set_model(self, model):
        self.model = model
