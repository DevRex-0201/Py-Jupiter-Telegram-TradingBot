const { Connection, Keypair, PublicKey } = require('@solana/web3.js');
const { Liquidity, TokenAmount, Token, Percent } = require('@raydium-io/raydium-sdk');

const devnetConnection = new Connection('https://api.devnet.solana.com');
// Split the PRIVATE_KEY environment variable to get an array of numbers
const privateKey = process.env.PRIVATE_KEY.split(',').map(num => parseInt(num, 10));
const wallet = Keypair.fromSecretKey(new Uint8Array(privateKey));

const OWNER = process.env.OWNER;
const TOKEN = process.env.TOKEN;
const SOL = process.env.SOL;

async function main() {
  const poolKeys = {
    id: new PublicKey(OWNER),
  };

  const tokenA = new Token(devnetConnection, new PublicKey(SOL), 9, wallet.publicKey);
  const tokenB = new Token(devnetConnection, new PublicKey(TOKEN), 6, wallet.publicKey);  

  const rawAmountIn = 1;
  const amountIn = new TokenAmount(tokenA, rawAmountIn * 10**tokenA.decimals, false);

  const slippage = new Percent(50, 10000);
  const poolInfo = await Liquidity.fetchInfo(devnetConnection, poolKeys);
  const { minAmountOut } = Liquidity.computeAmountOut(poolInfo, amountIn, tokenB, slippage);

  const { transaction, signers } = await Liquidity.makeSwapTransaction({
    connection: devnetConnection,
    poolKeys,
    userKeys: {
      owner: wallet.publicKey,
    },
    amountIn,
    amountOut: minAmountOut,
    fixedSide: 'in',
  });

  const signature = await devnetConnection.sendTransaction(transaction, [wallet, ...signers]);
  console.log(`Transaction hash: ${signature}`);

  await devnetConnection.confirmTransaction(signature);
  console.log(`Transaction confirmed: ${signature}`);
}

main().catch(error => {
  console.error(error);
});