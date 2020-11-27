const path = require('path');

const ROOT = path.resolve(__dirname, 'src');
const DESTINATION = path.resolve(__dirname, 'dist');

module.exports = {
    context: ROOT,
    target: 'node',

    mode: process.env.BUILD_MODE || 'development',
    entry: {
        index: './main.ts',
    },

    output: {
        filename: '[name].js',
        path: DESTINATION,
        libraryTarget: 'commonjs',
    },

    resolve: {
        extensions: ['.ts', '.js'],
        modules: [ROOT, 'node_modules'],
    },

    optimization: {
        minimize: false,
    },

    module: {
        rules: [
            /****************
             * PRE-LOADERS
             *****************/
            {
                enforce: 'pre',
                test: /\.js$/,
                use: 'source-map-loader',
            },
            {
                enforce: 'pre',
                test: /\.ts$/,
                exclude: /node_modules/,
                use: 'tslint-loader',
            },

            /****************
             * LOADERS
             *****************/
            {
                test: /\.ts$/,
                exclude: [/node_modules/],
                use: 'ts-loader',
            },
        ],
    },

    devtool: 'cheap-module-source-map',
    devServer: {},
};
