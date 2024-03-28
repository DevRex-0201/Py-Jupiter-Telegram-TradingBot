# swap.py
import base64
import requests
from solana.rpc.api import Client
from solders.keypair import Keypair
from solana.transaction import Transaction

def swap_sol_to_usdc(solana_rpc_endpoint, user_public_key, private_key_bytes, input_token, output_token, input_amount_lamports, slippage_bps):
    # Initialize the Solana RPC client
    connection = Client(solana_rpc_endpoint)

    # Get the quote for swapping
    quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_token}&outputMint={output_token}&amount={input_amount_lamports}&slippageBps={slippage_bps}"
    quote_response = requests.get(quote_url).json()

    # Get serialized transactions for the swap
    swap_response = requests.post(
        "https://quote-api.jup.ag/v6/swap",
        headers={'Content-Type': 'application/json'},
        json={
            "quoteResponse": quote_response,
            "userPublicKey": user_public_key,
            "wrapAndUnwrapSol": True,
        }
    ).json()
    swap_transaction = swap_response.get('swapTransaction')

    # Deserialize the transaction
    try:
        transaction_bytes = base64.b64decode(swap_transaction)
        transaction = Transaction.deserialize(transaction_bytes)
    except ValueError as e:
        print(f"Error deserializing transaction: {str(e)}")
        return {"error": str(e)}

    # Create a keypair from the provided private key bytes
    keypair = Keypair.from_secret_key(bytes(private_key_bytes))

    # Sign the transaction
    transaction.sign(keypair)

    # Send the transaction
    try:
        response = connection.send_raw_transaction(transaction.serialize())
        print("Transaction response:", response)
        return response
    except Exception as e:
        print(f"Error sending transaction: {str(e)}")
        return {"error": str(e)}
