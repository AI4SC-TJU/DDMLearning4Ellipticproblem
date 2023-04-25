import tensorflow.compat.v1 as tf
import numpy as np
import timeit
tf.disable_v2_behavior()
def u(x, a_1, a_2):
    return np.sin(a_1 * np.pi * x[:, 0:1]) * (np.cos(a_2 * np.pi * x[:, 1:2])- 1)

def u_x(x, a_1, a_2):
    return a_1 * np.pi * np.cos(a_1 * np.pi * x[:, 0:1]) * (np.cos(a_2 * np.pi * x[:, 1:2])- 1)

def u_y(x, a_1, a_2):
    return -a_2 * np.pi * np.sin(a_1 * np.pi * x[:, 0:1]) * np.sin(a_2 * np.pi * x[:, 1:2])

def u_xx(x, a_1, a_2):
    return - (a_1 * np.pi) ** 2 * np.sin(a_1 * np.pi * x[:, 0:1]) * (np.cos(a_2 * np.pi * x[:, 1:2])- 1)
def u_yy(x, a_1, a_2):
    return - (a_2 * np.pi) ** 2 * np.sin(a_1 * np.pi * x[:, 0:1]) * np.cos(a_2 * np.pi * x[:, 1:2])


class Sampler:
    # Initialize the class
    def __init__(self, dim, coords, func, name=None):
        self.dim = dim
        self.coords = coords
        self.func = func
        self.name = name

    def sample(self, N):
        x = self.coords[0:1, :] + (self.coords[1:2, :] - self.coords[0:1, :]) * np.random.rand(N, self.dim)
        y = self.func(x)
        return x, y

class Poisson2D:
    def __init__(self, args, layers, operator, ics_sampler, bcs_sampler, res_sampler, lam, model, stiff_ratio):
        self.args = args
        # Normalization constants
        X, _ = res_sampler.sample(np.int32(1e5))
        self.mu_X, self.sigma_X = X.mean(0), X.std(0)
        self.mu_x1, self.sigma_x1 = self.mu_X[0], self.sigma_X[0]
        self.mu_x2, self.sigma_x2 = self.mu_X[1], self.sigma_X[1]

        # Samplers
        self.operator = operator
        self.ics_sampler = ics_sampler
        self.bcs_sampler = bcs_sampler
        self.res_sampler = res_sampler

        # Helmoholtz constant
        self.lam = tf.constant(lam, dtype=tf.float32)

        # Mode
        self.model = model

        # Record stiff ratio
        self.stiff_ratio = stiff_ratio

        # Adaptive constant
        self.beta = 0.9
        if self.model in ['M1','M2']:
            self.adaptive_constant_val = np.array(40.0)
            self.adaptive_constant_robin_val = np.array(1.0)
        else:
            self.adaptive_constant_val = np.array(1.0)
            self.adaptive_constant_robin_val = np.array(1.0)        
        # Define Tensorflow session
        config = tf.ConfigProto(log_device_placement=True)
        config.gpu_options.allow_growth = True
        self.sess = tf.Session(config=config)
        # Initialize network weights and biases
        self.layers = layers
        self.weights, self.biases = self.initialize_NN(layers)

        if model in ['M3', 'M4']:
            # Initialize encoder weights and biases
            self.encoder_weights_1 = self.xavier_init([2, layers[1]])
            self.encoder_biases_1 = self.xavier_init([1, layers[1]])

            self.encoder_weights_2 = self.xavier_init([2, layers[1]])
            self.encoder_biases_2 = self.xavier_init([1, layers[1]])


        # Define placeholders and computational graph
        self.x1_u_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.x2_u_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.u_tf = tf.placeholder(tf.float32, shape=(None, 1))

        self.grad_x1_u_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.grad_x2_u_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.grad_u_tf = tf.placeholder(tf.float32, shape=(None, 2))       

        self.x1_bc1_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.x2_bc1_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.u_bc1_tf = tf.placeholder(tf.float32, shape=(None, 1))

        self.x1_bc2_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.x2_bc2_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.u_bc2_tf = tf.placeholder(tf.float32, shape=(None, 1))

        self.x1_bc3_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.x2_bc3_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.u_bc3_tf = tf.placeholder(tf.float32, shape=(None, 1))

        self.x1_bc4_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.x2_bc4_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.u_bc4_tf = tf.placeholder(tf.float32, shape=(None, 1))

        self.x1_r_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.x2_r_tf = tf.placeholder(tf.float32, shape=(None, 1))
        self.r_tf = tf.placeholder(tf.float32, shape=(None, 1))


        self.x1_test = tf.placeholder(tf.float32, shape=(None, 1))
        self.x2_test = tf.placeholder(tf.float32, shape=(None, 1))
        # Define placeholder for adaptive constant
        self.adaptive_constant_tf = tf.placeholder(tf.float32, shape=self.adaptive_constant_val.shape)
        self.adaptive_constant_robin_tf = tf.placeholder(tf.float32, shape=self.adaptive_constant_val.shape)

        # Evaluate predictions
        self.u_bc1_pred = self.net_u(self.x1_bc1_tf, self.x2_bc1_tf)
        self.u_bc2_pred = self.net_u(self.x1_bc2_tf, self.x2_bc2_tf) 
        self.u_bc3_pred = self.net_u(self.x1_bc3_tf, self.x2_bc3_tf)
        self.u_bc4_pred = self.net_u(self.x1_bc4_tf, self.x2_bc4_tf)
        self.u_bc2_pred = tf.gradients(self.u_bc2_pred , self.x1_bc2_tf)[0] + args.alpha * self.u_bc2_pred

        self.u_pred = self.net_u(self.x1_u_tf, self.x2_u_tf)
        self.r_pred = self.net_r(self.x1_r_tf, self.x2_r_tf)
        self.grad_u_pred = self.net_grad_u(self.grad_x1_u_tf, self.grad_x2_u_tf)
        x1_test = np.linspace(0, 0.5, 100)
        x2_test = np.linspace(0, 1 , 100)
        x1_test,  x2_test = np.meshgrid(x1_test, x2_test)
        x1_test = x1_test.reshape(-1,1)
        x2_test = x2_test.reshape(-1,1)
        self.test = np.hstack([x1_test, x2_test])
        # Boundary loss
        self.loss_bc1 = tf.reduce_mean(tf.square(self.u_bc1_tf - self.u_bc1_pred))
        self.loss_bc2 = tf.reduce_mean(tf.square(self.u_bc2_tf - self.u_bc2_pred))
        self.loss_bc3 = tf.reduce_mean(tf.square(self.u_bc3_tf - self.u_bc3_pred))
        self.loss_bc4 = tf.reduce_mean(tf.square(self.u_bc4_tf - self.u_bc4_pred))
        self.loss_bcs = self.adaptive_constant_tf * (self.loss_bc1 + self.loss_bc3 + self.loss_bc4)
        self.loss_bcs_robin = self.adaptive_constant_robin_tf * self.loss_bc2
        # Residual loss
        self.loss_res = tf.reduce_mean(tf.square(self.r_tf - self.r_pred))

        # Total loss
        self.loss = self.loss_res + self.loss_bcs + self.loss_bcs_robin



        # Define optimizer with learning rate schedule
        self.global_step = tf.Variable(0, trainable=False)
        starter_learning_rate = 1e-3
        #self.learning_rate = tf.train.exponential_decay(starter_learning_rate, self.global_step, 1000, 0.9, staircase=False)
        self.learning_rate = tf.train.piecewise_constant(self.global_step, [50000, 80000], values = [0.01, 0.001, 0.0001])
        
        # Passing global_step to minimize() will increment it at each step.
        self.train_op = tf.train.AdamOptimizer(self.learning_rate).minimize(self.loss, global_step=self.global_step)

        # Logger
        self.loss_res_log = []
        self.loss_bcs_log = []
        self.loss_bcs_robin_log = []
        self.train_loss_log = []
        self.test_loss_log = []
        self.test_loss_x_log = []
        self.test_loss_y_log = []


        self.saver = tf.train.Saver()

        # Generate dicts for gradients storage
        self.dict_gradients_res_layers = self.generate_grad_dict(self.layers)
        self.dict_gradients_bcs_layers = self.generate_grad_dict(self.layers)
        self.dict_gradients_bcs_robin_layers = self.generate_grad_dict(self.layers)
        # Gradients Storage
        self.grad_res = []
        self.grad_bcs = []
        self.grad_bcs_robin = []
        for i in range(len(self.layers) - 1):
            self.grad_res.append(tf.gradients(self.loss_res, self.weights[i])[0])
            self.grad_bcs.append(tf.gradients(self.loss_bcs, self.weights[i])[0])
            self.grad_bcs_robin.append(tf.gradients(self.loss_bcs_robin, self.weights[i])[0])
        
        # Compute and store the adaptive constant
        self.adaptive_constant_log = []
        self.adaptive_constant_list = []
        self.adaptive_constant_robin_log = []
        self.adaptive_constant_robin_list = []
        self.max_grad_res_list = []
        self.mean_grad_bcs_list = []
        self.mean_grad_bcs_robin_list = []
        for i in range(len(self.layers) - 1):
            self.max_grad_res_list.append(tf.reduce_max(tf.abs(self.grad_res[i]))) 
            self.mean_grad_bcs_list.append(tf.reduce_mean(tf.abs(self.grad_bcs[i])))
            self.mean_grad_bcs_robin_list.append(tf.reduce_mean(tf.abs(self.grad_bcs_robin[i])))

        self.max_grad_res = tf.reduce_max(tf.stack(self.max_grad_res_list))
        self.mean_grad_bcs = tf.reduce_mean(tf.stack(self.mean_grad_bcs_list))
        self.mean_grad_bcs_robin = tf.reduce_mean(tf.stack(self.mean_grad_bcs_robin_list))
        self.adaptive_constant = self.max_grad_res / self.mean_grad_bcs
        self.adaptive_constant_robin = self.max_grad_res / self.mean_grad_bcs_robin
        # Stiff Ratio
        if self.stiff_ratio:
            self.Hessian, self.Hessian_bcs, self.Hessian_res, self.Hessian_bcs_robin = self.get_H_op()
            self.eigenvalues, _ = tf.linalg.eigh(self.Hessian)
            self.eigenvalues_bcs, _ = tf.linalg.eigh(self.Hessian_bcs)
            self.eigenvalues_res, _ = tf.linalg.eigh(self.Hessian_res)
            self.eigenvalues_bcs_robin, _ = tf.linalg.eigh(self.Hessian_bcs_robin)
            self.eigenvalue_log = []
            self.eigenvalue_bcs_log = []
            self.eigenvalue_bcs_robin_log = []
            self.eigenvalue_res_log = []

        # Initialize Tensorflow variables
        init = tf.global_variables_initializer()
        self.sess.run(init)

     # Create dictionary to store gradients
    def generate_grad_dict(self, layers):
        num = len(layers) - 1
        grad_dict = {}
        for i in range(num):
            grad_dict['layer_{}'.format(i + 1)] = []
        return grad_dict

    # Save gradients
    def save_gradients(self, tf_dict):
        num_layers = len(self.layers)
        for i in range(num_layers - 1):
            grad_res_value, grad_bcs_value, grad_bcs_robin_value = self.sess.run([self.grad_res[i], self.grad_bcs[i], self.grad_bcs_robin[i]], feed_dict=tf_dict)

            # save gradients of loss_res and loss_bcs
            self.dict_gradients_res_layers['layer_' + str(i + 1)].append(grad_res_value.flatten())
            self.dict_gradients_bcs_layers['layer_' + str(i + 1)].append(grad_bcs_value.flatten())
            self.dict_gradients_bcs_robin_layers['layer_' + str(i + 1)].append(grad_bcs_robin_value.flatten())
        return None

    # Compute the Hessian
    def flatten(self, vectors):
        return tf.concat([tf.reshape(v, [-1]) for v in vectors], axis=0)

    def get_Hv(self, v):
        loss_gradients = self.flatten(tf.gradients(self.loss, self.weights))
        vprod = tf.math.multiply(loss_gradients,
                                 tf.stop_gradient(v))
        Hv_op = self.flatten(tf.gradients(vprod, self.weights))
        return Hv_op

    def get_Hv_res(self, v):
        loss_gradients = self.flatten(tf.gradients(self.loss_res,
                                                           self.weights))
        vprod = tf.math.multiply(loss_gradients,
                                 tf.stop_gradient(v))
        Hv_op = self.flatten(tf.gradients(vprod,
                                                  self.weights))
        return Hv_op

    def get_Hv_bcs(self, v):
        loss_gradients = self.flatten(tf.gradients(self.loss_bcs, self.weights))
        vprod = tf.math.multiply(loss_gradients,
                                 tf.stop_gradient(v))
        Hv_op = self.flatten(tf.gradients(vprod, self.weights))
        return Hv_op

    def get_Hv_bcs_robin(self, v):
        loss_gradients = self.flatten(tf.gradients(self.loss_bcs_robin, self.weights))
        vprod = tf.math.multiply(loss_gradients,
                                 tf.stop_gradient(v))
        Hv_op = self.flatten(tf.gradients(vprod, self.weights))
        return Hv_op
    def get_H_op(self):
        self.P = self.flatten(self.weights).get_shape().as_list()[0]
        H = tf.map_fn(self.get_Hv, tf.eye(self.P, self.P),
                      dtype='float32')
        H_bcs = tf.map_fn(self.get_Hv_bcs, tf.eye(self.P, self.P),
                      dtype='float32')
        H_res = tf.map_fn(self.get_Hv_res, tf.eye(self.P, self.P),
                          dtype='float32')
        H_bcs_robin = tf.map_fn(self.get_Hv_bcs_robin, tf.eye(self.P, self.P),
                          dtype='float32')
        return H, H_bcs, H_res, H_bcs_robin

    # Xavier initialization
    def xavier_init(self,size):
        in_dim = size[0]
        out_dim = size[1]
        xavier_stddev = 1. / np.sqrt((in_dim + out_dim) / 2.)
        return tf.Variable(tf.random_normal([in_dim, out_dim], dtype=tf.float32) * xavier_stddev,
                           dtype=tf.float32)

    # Initialize network weights and biases using Xavier initialization
    def initialize_NN(self, layers):
        weights = []
        biases = []
        num_layers = len(layers)
        for l in range(0, num_layers - 1):
            W = self.xavier_init(size=[layers[l], layers[l + 1]])
            b = tf.Variable(tf.zeros([1, layers[l + 1]], dtype=tf.float32), dtype=tf.float32)
            weights.append(W)
            biases.append(b)
        return weights, biases

    # Evaluates the forward pass
    def forward_pass(self, H):
        if self.model in ['M1', 'M2']:
            num_layers = len(self.layers)
            for l in range(0, num_layers - 2):
                W = self.weights[l]
                b = self.biases[l]
                H = tf.tanh(tf.add(tf.matmul(H, W), b))
            W = self.weights[-1]
            b = self.biases[-1]
            H = tf.add(tf.matmul(H, W), b)
            return H

        if self.model in ['M3', 'M4']:
            num_layers = len(self.layers)
            encoder_1 = tf.tanh(tf.add(tf.matmul(H, self.encoder_weights_1), self.encoder_biases_1))
            encoder_2 = tf.tanh(tf.add(tf.matmul(H, self.encoder_weights_2), self.encoder_biases_2))

            for l in range(0, num_layers - 2):
                W = self.weights[l]
                b = self.biases[l]
                H = tf.math.multiply(tf.tanh(tf.add(tf.matmul(H, W), b)), encoder_1) + \
                    tf.math.multiply(1 - tf.tanh(tf.add(tf.matmul(H, W), b)), encoder_2)

            W = self.weights[-1]
            b = self.biases[-1]
            H = tf.add(tf.matmul(H, W), b)
            return H

    # Forward pass for u
    def net_u(self, x1, x2):
        u = self.forward_pass(tf.concat([x1, x2], 1))
        return u
    # the gradient of u:
    def net_grad_u(self, x1, x2):
        u = self.net_u(x1, x2)
        grad_x = tf.gradients(u, x1)[0]
        grad_y = tf.gradients(u, x2)[0]
        return tf.concat([grad_x, grad_y], 1)
    # Forward pass for residual
    def net_r(self, x1, x2):
        u = self.net_u(x1, x2)
        residual = self.operator(u, x1, x2,
                                 self.lam,
                                 self.sigma_x1,
                                 self.sigma_x2)
        return residual

    # Feed minibatch
    def fetch_minibatch(self, sampler, N):
        X, Y = sampler.sample(N)
        X = (X - self.mu_X) / self.sigma_X
        return X, Y

    # Trains the model by minimizing the MSE loss
    def train(self, nIter=10000, batch_size=128):

        start_time = timeit.default_timer()
        for it in range(nIter):
            # Fetch boundary mini-batches
            X_bc1_batch, u_bc1_batch = self.fetch_minibatch(self.bcs_sampler[0], batch_size)
            X_bc2_batch, u_bc2_batch = self.fetch_minibatch(self.bcs_sampler[1], batch_size)
            X_bc3_batch, u_bc3_batch = self.fetch_minibatch(self.bcs_sampler[2], batch_size)
            X_bc4_batch, u_bc4_batch = self.fetch_minibatch(self.bcs_sampler[3], batch_size)

            # Fetch residual mini-batch
            X_res_batch, f_res_batch = self.fetch_minibatch(self.res_sampler, batch_size)

            # Define a dictionary for associating placeholders with data
            tf_dict = {self.x1_bc1_tf: X_bc1_batch[:, 0:1], self.x2_bc1_tf: X_bc1_batch[:, 1:2],
                       self.u_bc1_tf: u_bc1_batch,
                       self.x1_bc2_tf: X_bc2_batch[:, 0:1], self.x2_bc2_tf: X_bc2_batch[:, 1:2],
                       self.u_bc2_tf: u_bc2_batch,
                       self.x1_bc3_tf: X_bc3_batch[:, 0:1], self.x2_bc3_tf: X_bc3_batch[:, 1:2],
                       self.u_bc3_tf: u_bc3_batch,
                       self.x1_bc4_tf: X_bc4_batch[:, 0:1], self.x2_bc4_tf: X_bc4_batch[:, 1:2],
                       self.u_bc4_tf: u_bc4_batch,
                       self.grad_x1_u_tf: X_res_batch[:, 0:1], self.grad_x2_u_tf: X_res_batch[:, 1:2],
                       self.x1_r_tf: X_res_batch[:, 0:1], self.x2_r_tf: X_res_batch[:, 1:2], self.r_tf: f_res_batch,
                       self.adaptive_constant_tf:  self.adaptive_constant_val,
                       self.adaptive_constant_robin_tf:  self.adaptive_constant_robin_val
                       }

            # Run the Tensorflow session to minimize the loss
            self.sess.run(self.train_op, tf_dict)

            # Compute the eigenvalues of the Hessian of losses
            if self.stiff_ratio:
                if it % 1000 == 0:
                    print("Eigenvalues information stored ...")
                    eigenvalues, eigenvalues_bcs, eigenvalues_res, eigenvalues_bcs_robin = self.sess.run([self.eigenvalues,
                                                                                   self.eigenvalues_bcs,
                                                                                   self.eigenvalues_res,
                                                                                   self.eigenvalues_bcs_robin], tf_dict)

                    # Log eigenvalues
                    self.eigenvalue_log.append(eigenvalues)
                    self.eigenvalue_bcs_log.append(eigenvalues_bcs)
                    self.eigenvalue_res_log.append(eigenvalues_res)
                    self.eigenvalue_bcs_robin_log.append(eigenvalues_bcs_robin)
            # Print
            if it % 10 == 0:
                elapsed = timeit.default_timer() - start_time
                loss_value = self.sess.run(self.loss, tf_dict)
                loss_bcs_value, loss_res_value, loss_bcs_robin_value = self.sess.run([self.loss_bcs, self.loss_res, self.loss_bcs_robin], tf_dict)

                self.loss_bcs_log.append(loss_bcs_value /  self.adaptive_constant_val)
                self.loss_bcs_robin_log.append(loss_bcs_robin_value /  self.adaptive_constant_robin_val)
                self.loss_res_log.append(loss_res_value)

                # Compute and Print adaptive weights during training
                if self.model in ['M2', 'M4']:
                    adaptive_constant_value = self.sess.run(self.adaptive_constant, tf_dict)
                    self.adaptive_constant_val = adaptive_constant_value * (1.0 - self.beta) \
                                                 + self.beta * self.adaptive_constant_val
                    adaptive_constant_robin_value = self.sess.run(self.adaptive_constant_robin, tf_dict)
                    self.adaptive_constant_robin_val = adaptive_constant_robin_value * (1.0 - self.beta) \
                                                 + self.beta * self.adaptive_constant_robin_val
                self.adaptive_constant_log.append(self.adaptive_constant_val)
                self.adaptive_constant_robin_log.append(self.adaptive_constant_robin_val)

                print('It: %d, Loss: %.3e, Loss_bcs: %.3e, Loss_bcs_robin: %.3e, Loss_res: %.3e, Adaptive_Constant: %.2f ,Adaptive_Constant_robin: %.2f,Time: %.2f' %
                      (it, loss_value, loss_bcs_value, loss_bcs_robin_value, loss_res_value, self.adaptive_constant_val, self.adaptive_constant_robin_val, elapsed))
                start_time = timeit.default_timer()


                self.test_loss = np.mean(np.power(self.predict_u(self.test) - u(self.test, 2, 2), 2))
                self.test_loss_x = np.mean(np.power(self.predict_grad_u(self.test)[: , 0:1] - u_x(self.test, 2, 2), 2))
                self.test_loss_y = np.mean(np.power(self.predict_grad_u(self.test)[: , 1:2] - u_y(self.test, 2, 2), 2))

                self.train_loss_log.append(self.sess.run(self.loss, tf_dict))
                self.test_loss_log.append(self.test_loss)
                self.test_loss_x_log.append(self.test_loss_x)
                self.test_loss_y_log.append(self.test_loss_y)
            
            # Store gradients
            if it % 10000 == 0:
                self.save_gradients(tf_dict)
                print("Gradients information stored ...")

                # Evaluates predictions at test points

    # Evaluates predictions at test points
    def predict_u(self, X_star):
        X_star = (X_star - self.mu_X) / self.sigma_X
        tf_dict = {self.x1_u_tf: X_star[:, 0:1], self.x2_u_tf: X_star[:, 1:2]}
        u_star = self.sess.run(self.u_pred, tf_dict)
        return u_star
    def predict_grad_u(self, X_star):
        X_star = (X_star - self.mu_X) / self.sigma_X
        tf_dict = {self.grad_x1_u_tf: X_star[:, 0:1], self.grad_x2_u_tf: X_star[:, 1:2]}
        grad_u_star = self.sess.run(self.grad_u_pred, tf_dict)
        return grad_u_star
    def predict_r(self, X_star):
        X_star = (X_star - self.mu_X) / self.sigma_X
        tf_dict = {self.x1_r_tf: X_star[:, 0:1], self.x2_r_tf: X_star[:, 1:2]}
        r_star = self.sess.run(self.r_pred, tf_dict)
        return r_star