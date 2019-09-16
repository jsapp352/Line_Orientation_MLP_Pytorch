# A module that provides an interface between a software MLP model
#  and an LTspice hardware simulation.

import numpy
import re
import subprocess
from random import randrange
from operator import attrgetter

from pprint import pprint

_v_plus = 7
_v_minus = -7.0

_v_in_max = 1.5
_v_in_min = -1.5

_pot_tolerance = 0.20
_pot_tap_count = 128
_pots_per_chip = 4

_r_total_ohms = 5000

_output_filename = 'MLP_netlist.net'
_result_filename = _output_filename[:-4] + '.log'
_ltspice_path = '"C:\\Program Files\\LTC\\LTspiceXVII\\XVIIx64.exe" -b '

_simulation_includes_input_buffers = False

class MLP_Circuit_Layer():
    def __init__(self, neuron_layer, input_nodes, layer_number, r_total_ohms, digital_pot_factory):
        self.neuron_layer = neuron_layer
        self.neuron_count = neuron_layer.neuron_count
        self.inputs_per_neuron = neuron_layer.inputs_per_neuron

        #DEBUG
        # print(f'input nodes: {input_nodes}')

        self.input_nodes = [f'Synapse_{layer_number}_{x}_in' for x in range(0, self.inputs_per_neuron)] if layer_number == 0 else input_nodes
        self.output_nodes = [f'Neuron_{layer_number}_{x}_out' for x in range(0, self.neuron_count)]

        self.layer_number = layer_number
        self.r_total_ohms = r_total_ohms
        self.max_weight = self.neuron_layer.max_weight

        self.digital_pots = [[digital_pot_factory.pot(self.max_weight) for j in range(0, self.neuron_count)] for i in range(0, self.inputs_per_neuron)]
        self.synapses_r_neg = None
        self.synapses_r_pos = None

        self.update_synapse_weights()

    def update_synapse_weights(self):
        for i in range(0, self.inputs_per_neuron-1):
            for j in range(0, self.neuron_count-1):
                self.digital_pots[j][i].set_weight(self.neuron_layer.synaptic_weights[j][i])
        

        self.synapses_r_neg = numpy.asarray([[x.r_neg for x in y] for y in self.digital_pots])

        self.synapses_r_pos = self.synapses_r_neg = numpy.asarray([[x.r_pos for x in y] for y in self.digital_pots])
    
    def create_layer_subcircuit(self):
        neuron_lines = []
        synapse_lines = []
        
        inputs = self.input_nodes
        
        for i in range(0, self.neuron_count):
            n_id = f'{self.layer_number}_{i}'            

            neuron_lines += self.create_neuron_subcircuit(n_id, self.output_nodes[i])

            for j in range(0, self.inputs_per_neuron):
                s_id = f'{n_id}_{j}'
                r_pos = f'{self.synapses_r_pos[j][i]}'
                r_neg = f'{self.synapses_r_neg[j][i]}'

                #DEBUG
                # print(f'j: {j}. inputs[j]: {inputs[j]}')
                
                input = inputs[j]
                
                synapse_lines += self.create_synapse_subcircuit(n_id, s_id, input, r_pos, r_neg)

        lines = neuron_lines + synapse_lines

        return lines

    def create_neuron_subcircuit(self, n_id, output):
        lines = []

        lines.append(f'X_Sum_{n_id} Neuron_{n_id}_008 Neuron_{n_id}_004 V+ V- Neuron_{n_id}_005 TL084')
        lines.append(f'X_Activation_{n_id} 0 Neuron_{n_id}_001 V+ V- {output} TL084')
        lines.append(f'R**_{n_id} Neuron_{n_id}_005 Neuron_{n_id}_004 {90 / self.inputs_per_neuron}k tol=5')
        lines.append(f'R4_{n_id} Neuron_{n_id}_001 Neuron_{n_id}_005 20k tol=5')
        lines.append(f'R8_{n_id} Neuron_{n_id}_003 Neuron_{n_id}_001 100k tol=5')
        lines.append(f'R9_{n_id} Neuron_{n_id}_003 {output} 3.3k tol=5')
        lines.append(f'R12_{n_id} Neuron_{n_id}_008 0 10k tol=5')
        lines.append(f'D1_{n_id} Neuron_{n_id}_001 Neuron_{n_id}_002 1N4001')
        lines.append(f'D2_{n_id} Neuron_{n_id}_002 Neuron_{n_id}_003 1N4001')
        lines.append(f'D3_{n_id} Neuron_{n_id}_006 Neuron_{n_id}_001 1N4001')
        lines.append(f'D4_{n_id} Neuron_{n_id}_003 Neuron_{n_id}_006 1N4001')

        lines.append(f'E_{n_id} {output}` 0 {output} 0 -1')
        lines.append('\n')

        return lines

    def create_synapse_subcircuit(self, n_id, s_id, input, r_pos, r_neg):
        simulation_includes_input_buffers = _simulation_includes_input_buffers

        lines  = []

        if simulation_includes_input_buffers:
            lines.append(f'XV_buff_{s_id} {input} buff_out_{s_id} V+ V- buff_out_{s_id} TL084')
            lines.append(f'XV_buff`_{s_id} 0 buff`_inv_{s_id} V+ V- buff`_out_{s_id} TL084')
            lines.append(f'R1_buff`_{s_id} {input} buff`_inv_{s_id} 100k')
            lines.append(f'R2_buff`_{s_id} buff`_inv_{s_id} buff_out_{s_id} 100k')

            lines.append(f'R_in_{s_id} buff_out_{s_id} Input_{s_id} {r_pos}')
            lines.append(f'R_in`_{s_id} buff`_out_{s_id} Input_{s_id} {r_neg}')
            lines.append(f'R_in_{s_id}_series Input_{s_id} Neuron_{n_id}_004 5k')
        else:
            lines.append(f'R_in_{s_id} {input} Input_{s_id} {r_pos}')
            lines.append(f'R_in`_{s_id} {input}` Input_{s_id} {r_neg}')
            lines.append(f'R_in_{s_id}_series Input_{s_id} Neuron_{n_id}_004 5K')

        lines.append('\n')

        return lines

class DigitalPot():
    def __init__(self, r_total_ohms, tap_count, max_weight):
        self.r_total_ohms = r_total_ohms
        self.tap_count = tap_count
        self.max_weight = max_weight

        # Throw-away initial value
        self.set_weight(0)

    def set_weight(self, weight):
        wiper_position = min(self.tap_count-1, max(1, int((weight / self.max_weight + 1) / 2 * self.tap_count)))
        self.r_neg = wiper_position / self.tap_count * self.r_total_ohms
        self.r_pos = self.r_total_ohms - self.r_neg



class DigitalPotFactory():
    def __init__(self, r_total_ohms, tap_count, pots_per_chip, tolerance):
        self.r_total_ohms = r_total_ohms
        self.tap_count = tap_count
        self.tolerance = tolerance
        self.pots_per_chip = pots_per_chip
        self.pot_counter = 1
        self.chip_resistance = r_total_ohms

    def pot(self, max_weight):
        if (self.pot_counter == 1):
            self.chip_resistance = randrange(int((1.0-self.tolerance) * self.r_total_ohms), int((1.0+self.tolerance) * self.r_total_ohms))

        self.pot_counter = (self.pot_counter + 1) if (self.pot_counter < self.pots_per_chip) else 1

        return DigitalPot(self.chip_resistance, self.tap_count, max_weight)

        
        

class MLP_Circuit():
    def __init__(self, neural_network):
        self.v_plus = _v_plus
        self.v_minus = _v_minus
        
        self.v_in_max = _v_in_max
        self.v_in_min = _v_in_min
        
        self.r_total_ohms = _r_total_ohms
        
        self.output_filename = _output_filename
        self.result_filename = _result_filename
        self.ltspice_path = _ltspice_path

        self.digital_pot_factory = DigitalPotFactory(_r_total_ohms, _pot_tap_count, _pots_per_chip, _pot_tolerance)
        
        self.neural_network = neural_network
        self.hardware_layers = []
        self.initialize_hardware_layers()

        self.power_sources = {}
        self.power_sources['V+'] = _v_plus
        self.power_sources['V-'] = _v_minus

        self.input_sources = []

    
    def initialize_hardware_layers(self):
        input_nodes = None

        for idx,model_layer in enumerate(self.neural_network.neuron_layers):
            self.hardware_layers.append(MLP_Circuit_Layer(model_layer, input_nodes, idx, self.r_total_ohms, self.digital_pot_factory))
            print(f'Layer {idx} output nodes: {self.hardware_layers[idx].output_nodes}')
            input_nodes = self.hardware_layers[idx].output_nodes
        
        for i in range(1, len(self.hardware_layers)):
            self.hardware_layers[i].input_nodes = self.hardware_layers[i-1].output_nodes


    def update_input_sources(self, input_array):
        # print('Update_input_sources() input_array:')
        # pprint(input_array)
        # print('\n')

        inputs = input_array.tolist()

        v_in_range = self.v_in_max - self.v_in_min

        v_in_center = v_in_range / 2 + self.v_in_min
            
        map_input = lambda x: x * v_in_range / 2 + v_in_center

        self.input_sources = [map_input(x) for x in inputs]

        # pprint(self.input_sources)

    def create_header(self):
        lines = []

        lines.append('.model D D')
        lines.append('.lib D:\\Users\\jsapp\\Documents\\LTspiceXVII\\lib\\cmp\\standard.dio')
        lines.append('.include TL084.txt')
        lines.append('.include 1N4001.txt')
        
        lines.append('\n')

        return lines

    def create_footer(self):
        lines = []
        
        lines.append('.tran 0 1000p')
        lines.append('.options plotwinsize=0 trtol=7')

        # Skip N-R iterative solving
        lines.append('.options noopiter')

        # Skip gmin stepping
        lines.append('.options gminsteps=0')

        lines.append('.end')

        lines.append('\n')

        return lines
    
    def create_measurements(self):
        lines = []
        
        for layer in self.hardware_layers:
            for node in layer.output_nodes:
                lines.append(f'.save V({node})')

        for layer in self.hardware_layers:
            for node in layer.output_nodes:
                lines.append(f'.measure V{node} avg V({node})')

        #DEBUG
        lines.append('\n')
        for layer in self.hardware_layers:
            for node in layer.output_nodes:
                pattern = re.compile('(Neuron_\\d+_\\d+)')
                activation_input_node = f'{pattern.search(node)[0]}_005'
                lines.append(f'.save V({activation_input_node})')
                lines.append(f'.measure V{activation_input_node} avg V({activation_input_node})')
        
        lines.append('\n')

        return lines
    
    def create_source_definitions(self):
        simulation_includes_input_buffers = _simulation_includes_input_buffers

        lines = []
        i = 0

        for node in self.power_sources:
            lines.append(f'V{i} {node} 0 {self.power_sources[node]}V Rser=0.1')
            i += 1
        
        lines.append('\n')

        for idx,voltage in enumerate(self.input_sources):
            node = self.hardware_layers[0].input_nodes[idx]
            lines.append(f'V{i} {node} 0 {voltage} Rser=0.1')
            
            # If input buffers are not included in the simulation, add voltage sources for inverted input values
            if not simulation_includes_input_buffers:
                lines.append(f'V{i}` {node}` 0 {voltage * (-1)} Rser=0.1')
            i += 1

        lines.append('\n')

        return lines
    
    def create_netlist(self):
        lines = []

        lines += self.create_header()

        for layer in self.hardware_layers:
            lines += layer.create_layer_subcircuit()
        
        lines += self.create_source_definitions()
        lines += self.create_measurements()
        lines += self.create_footer()

        with open(self.output_filename, 'w') as f:
            for line in lines:
                f.write(line)
                f.write('\n')

    def run_simulation(self):
        command_string = self.ltspice_path + self.output_filename
        subprocess.check_call(command_string)

    def get_outputs(self):
        outputs = []

        with open(self.result_filename, 'r') as f:
            result = f.read()
            
            for layer in self.hardware_layers:
                output_voltages = []

                for node in layer.output_nodes:
                    pattern = re.compile(
                        f'({node.lower()}\)\)\=)(-?\d+\.?\d*e?-?\d*)(\s)')
                    
                    match = pattern.search(result)

                    if match == None:
                        return False, None

                    output_voltages.append(float(match[2]))

                #DEV Break this normalization formula out into its own function
                outputs.append((numpy.asarray(output_voltages) + self.v_in_max) / (2 * self.v_in_max))
                # pprint(outputs[-1])

        # pprint(numpy.asarray(outputs))
        return True, numpy.asarray(outputs)

    def think(self, inputs):
        # print('Ckt.Think() inputs:')
        # pprint(inputs)
        # print('\n')
        # print('Ckt.Think() inputs.tolist():')
        # pprint(inputs.tolist())
        # print('\n')

        self.update_input_sources(inputs)

        for layer in self.hardware_layers:
            layer.update_synapse_weights()
        
        self.create_netlist()
        
        success = False
        attempts = 5
        while success == False and attempts > 0:
            self.run_simulation()               
            success, outputs = self.get_outputs()
            attempts -= 1

        print(outputs)

        return outputs







    

    
